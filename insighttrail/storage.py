import datetime
import glob
import json
import os
from collections import deque

try:
    from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, MetaData, String, Table, Text, create_engine, func, select
except ImportError:  # SQLAlchemy is optional and only required for DB logging.
    Boolean = Column = DateTime = Float = Integer = JSON = MetaData = String = Table = Text = create_engine = func = select = None


DEFAULT_DB_COLUMNS = {
    'created_at': {'source': 'timestamp', 'type': 'datetime'},
    'trace_id': {'source': 'trace_id', 'type': 'string'},
    'level': {'source': 'level', 'type': 'string', 'length': 32},
    'method': {'source': 'request.method', 'type': 'string', 'length': 16},
    'path': {'source': 'request.path', 'type': 'text'},
    'status_code': {'source': 'request.status', 'type': 'integer'},
    'duration_ms': {'source': 'request.duration_ms', 'type': 'float'},
    'client_ip': {'source': 'request.client', 'type': 'string'},
    'error_type': {'source': 'error.type', 'type': 'string'},
    'error_message': {'source': 'error.message', 'type': 'text'},
    'payload_json': {'source': '$', 'type': 'json'},
}


def _copy_columns(columns):
    return {name: dict(spec) for name, spec in columns.items()}


def _infer_column_for_source(columns, source):
    for column_name, spec in columns.items():
        if spec.get('source') == source:
            return column_name
    return None


def normalize_db_config(db_config):
    raw_config = dict(db_config or {})
    if not raw_config.get('url'):
        raise ValueError("db_config['url'] is required when log_storage='db'.")

    user_columns = raw_config.get('columns')
    if user_columns:
        columns = _copy_columns(user_columns)
        payload_column = raw_config.get('payload_column') or _infer_column_for_source(columns, '$')
        timestamp_column = raw_config.get('timestamp_column') or _infer_column_for_source(columns, 'timestamp')
    else:
        columns = _copy_columns(DEFAULT_DB_COLUMNS)
        payload_column = raw_config.get('payload_column') or 'payload_json'
        timestamp_column = raw_config.get('timestamp_column') or 'created_at'

    table_name = raw_config.get('table') or 'insighttrail_logs'
    schema = raw_config.get('schema')
    if schema is None and isinstance(table_name, str) and '.' in table_name:
        schema, table_name = table_name.split('.', 1)

    return {
        'url': raw_config['url'],
        'table': table_name,
        'schema': schema,
        'auto_create': raw_config.get('auto_create', True),
        'id_column': raw_config.get('id_column') or 'id',
        'timestamp_column': timestamp_column,
        'payload_column': payload_column,
        'columns': columns,
        'engine_options': dict(raw_config.get('engine_options') or {}),
    }


def get_source_value(entry, source):
    if source == '$':
        return entry
    if not source:
        return None

    value = entry
    for part in source.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


def set_source_value(entry, source, value):
    if not source or source == '$':
        return

    current = entry
    parts = source.split('.')
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = _json_safe(value)


def _json_safe(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _parse_datetime(value):
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, datetime.date):
        dt = datetime.datetime.combine(value, datetime.time.min)
    elif isinstance(value, str):
        normalized = value.strip().replace('Z', '+00:00')
        dt = datetime.datetime.fromisoformat(normalized)
    else:
        return None

    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _coerce_value(value, value_type):
    if value is None:
        return None


    normalized_type = str(value_type or 'string').lower()

    if normalized_type in ('json_text', 'json_string'):
        return json.dumps(_json_safe(value), default=str)
    if normalized_type in ('json', 'dict'):
        return _json_safe(value)
    if normalized_type in ('datetime', 'timestamp'):
        try:
            return _parse_datetime(value)
        except (TypeError, ValueError):
            return None
    if normalized_type in ('integer', 'int'):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if normalized_type in ('float', 'number', 'decimal'):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if normalized_type in ('boolean', 'bool'):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'y')
        return bool(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_safe(value), default=str)
    return str(value)


def _decode_payload(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return _json_safe(value)
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return _json_safe(decoded)
        except (TypeError, ValueError):
            return None
    return None


def _safe_limit(limit):
    return max(1, int(limit))


class FileLogStore:
    def __init__(self, log_file, cache_size=None):
        self.log_file = log_file
        self._log_cache = deque(maxlen=cache_size)
        self._log_file_offset = 0
        self._next_log_id = 1

    def _refresh_log_cache(self):
        try:
            if not self.log_file or not os.path.exists(self.log_file):
                return

            current_size = os.path.getsize(self.log_file)
            if current_size < self._log_file_offset:
                self._log_file_offset = 0
                self._log_cache.clear()
                self._next_log_id = 1

            with open(self.log_file, 'r', encoding='utf-8', errors='replace') as handle:
                handle.seek(self._log_file_offset)
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        log_entry = json.loads(line)
                        log_entry['_id'] = self._next_log_id
                        self._next_log_id += 1
                        self._log_cache.append(log_entry)
                    except (json.JSONDecodeError, ValueError):
                        continue
                self._log_file_offset = handle.tell()
        except Exception as exc:
            print(f"Error reading log file: {exc}")

    def all_cached(self):
        self._refresh_log_cache()
        return list(self._log_cache)

    def get_page(self, limit=100, cursor=None):
        self._refresh_log_cache()
        safe_limit = _safe_limit(limit)
        logs = list(self._log_cache)

        if cursor is not None:
            cursor_id = int(cursor)
            filtered = [log for log in logs if int(log.get('_id', 0)) > cursor_id]
            page = filtered[:safe_limit]
            has_more = len(filtered) > len(page)
        else:
            page = logs[-safe_limit:]
            has_more = len(logs) > len(page)

        next_cursor = page[-1]['_id'] if page else (cursor if cursor is not None else 0)
        return {
            'logs': page,
            'cursor': next_cursor,
            'has_more': has_more,
        }

    def search_by_trace_id(self, trace_id):
        logs = self.all_cached()
        if not trace_id:
            return logs
        return [log for log in logs if log.get('trace_id') == trace_id]

    def _log_files(self):
        if not self.log_file:
            return []
        log_dir = os.path.dirname(self.log_file) or '.'
        base_name = os.path.basename(self.log_file)
        files = glob.glob(os.path.join(log_dir, f"{base_name}*"))
        return sorted([path for path in files if os.path.isfile(path)], key=os.path.getmtime)

    def collect_for_range(self, start_dt, end_dt, parse_datetime, max_rows):
        rows = []
        for file_path in self._log_files():
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            ts_raw = entry.get('timestamp')
                            if not ts_raw:
                                continue
                            ts = parse_datetime(ts_raw)
                            if start_dt <= ts <= end_dt:
                                entry['_parsed_ts'] = ts
                                rows.append(entry)
                                if len(rows) >= max_rows:
                                    break
                        except Exception:
                            continue
                if len(rows) >= max_rows:
                    break
            except IOError:
                continue

        rows.sort(key=lambda row: row.get('_parsed_ts', datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)))
        return rows

    def estimate_for_range(self, start_dt, end_dt, parse_datetime, max_rows):
        count = 0
        for file_path in self._log_files():
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            ts_raw = entry.get('timestamp')
                            if not ts_raw:
                                continue
                            ts = parse_datetime(ts_raw)
                            if start_dt <= ts <= end_dt:
                                count += 1
                                if count >= max_rows:
                                    return count
                        except Exception:
                            continue
            except IOError:
                continue
        return count


class SQLAlchemyLogStore:
    def __init__(self, db_config):
        if create_engine is None:
            raise RuntimeError("SQLAlchemy is required for database logging. Install with: pip install insighttrail[db]")

        self.config = normalize_db_config(db_config)
        self.columns = self.config['columns']
        self.id_column = self.config.get('id_column')
        self.timestamp_column = self.config.get('timestamp_column')
        self.payload_column = self.config.get('payload_column')
        self.trace_column = _infer_column_for_source(self.columns, 'trace_id')

        engine_options = self.config.get('engine_options') or {}
        engine_options.setdefault('pool_pre_ping', True)
        self.engine = create_engine(self.config['url'], **engine_options)
        self.metadata = MetaData()
        self.table = self._load_table()

        if not self.id_column or self.id_column not in self.table.c:
            self.id_column = None
        if not self.timestamp_column or self.timestamp_column not in self.table.c:
            self.timestamp_column = None
        if not self.payload_column or self.payload_column not in self.table.c:
            self.payload_column = None
        if not self.trace_column or self.trace_column not in self.table.c:
            self.trace_column = None
        self.timestamp_column_type = (self.columns.get(self.timestamp_column) or {}).get('type')

        missing_columns = [name for name in self.columns if name not in self.table.c]
        if missing_columns:
            raise ValueError(
                "Configured DB log column(s) do not exist in table "
                f"{self.config['table']}: {', '.join(sorted(missing_columns))}"
            )

    def _load_table(self):
        if self.config.get('auto_create'):
            table = self._build_table_definition()
            self.metadata.create_all(self.engine, tables=[table])
            return table

        return Table(
            self.config['table'],
            self.metadata,
            schema=self.config.get('schema'),
            autoload_with=self.engine,
        )

    def _build_table_definition(self):
        table_columns = []
        if self.config.get('id_column') and self.config['id_column'] not in self.columns:
            table_columns.append(Column(self.config['id_column'], Integer, primary_key=True, autoincrement=True))

        for column_name, spec in self.columns.items():
            table_columns.append(Column(column_name, self._column_type(spec)))

        return Table(
            self.config['table'],
            self.metadata,
            *table_columns,
            schema=self.config.get('schema'),
        )

    def _column_type(self, spec):
        value_type = str(spec.get('type') or 'string').lower()
        if value_type in ('integer', 'int'):
            return Integer()
        if value_type in ('float', 'number', 'decimal'):
            return Float()
        if value_type in ('datetime', 'timestamp'):
            return DateTime()
        if value_type in ('text', 'json_text', 'json_string'):
            return Text()
        if value_type in ('json', 'dict'):
            return JSON()
        if value_type in ('boolean', 'bool'):
            return Boolean()
        return String(int(spec.get('length') or 255))

    def write(self, entry):
        values = {}
        for column_name, spec in self.columns.items():
            if 'value' in spec:
                value = spec.get('value')
            else:
                value = get_source_value(entry, spec.get('source'))
            if value is None and 'default' in spec:
                value = spec.get('default')
            values[column_name] = _coerce_value(value, spec.get('type'))

        with self.engine.begin() as connection:
            connection.execute(self.table.insert().values(**values))

    def get_page(self, limit=100, cursor=None):
        safe_limit = _safe_limit(limit)
        rows = []

        with self.engine.connect() as connection:
            if self.id_column:
                id_col = self.table.c[self.id_column]
                statement = select(self.table)
                if cursor is not None:
                    statement = statement.where(id_col > int(cursor)).order_by(id_col.asc()).limit(safe_limit)
                    rows = connection.execute(statement).mappings().all()
                else:
                    statement = statement.order_by(id_col.desc()).limit(safe_limit)
                    rows = list(connection.execute(statement).mappings().all())
                    rows.reverse()
            else:
                statement = select(self.table)
                if self.timestamp_column:
                    statement = statement.order_by(self.table.c[self.timestamp_column].desc())
                statement = statement.limit(safe_limit)
                rows = list(connection.execute(statement).mappings().all())
                rows.reverse()

        page = [self._row_to_entry(row, fallback_id=index + 1) for index, row in enumerate(rows)]
        next_cursor = page[-1].get('_id', 0) if page else (cursor if cursor is not None else 0)
        if not self.id_column:
            next_cursor = 0
        return {
            'logs': page,
            'cursor': next_cursor,
            'has_more': len(page) == safe_limit,
        }

    def search_by_trace_id(self, trace_id):
        if not trace_id:
            return []

        with self.engine.connect() as connection:
            statement = select(self.table)
            if self.trace_column:
                statement = statement.where(self.table.c[self.trace_column] == trace_id)
            if self.id_column:
                statement = statement.order_by(self.table.c[self.id_column].asc())
            elif self.timestamp_column:
                statement = statement.order_by(self.table.c[self.timestamp_column].asc())
            statement = statement.limit(3000)
            rows = connection.execute(statement).mappings().all()

        entries = [self._row_to_entry(row, fallback_id=index + 1) for index, row in enumerate(rows)]
        if self.trace_column:
            return entries
        return [entry for entry in entries if entry.get('trace_id') == trace_id]

    def collect_for_range(self, start_dt, end_dt, parse_datetime, max_rows):
        if not self.timestamp_column:
            return []

        rows = self._rows_for_range(start_dt, end_dt, max_rows)
        entries = []
        for index, row in enumerate(rows):
            entry = self._row_to_entry(row, fallback_id=index + 1)
            ts_raw = entry.get('timestamp')
            if ts_raw:
                try:
                    entry['_parsed_ts'] = parse_datetime(ts_raw)
                except Exception:
                    pass
            entries.append(entry)
        return entries

    def estimate_for_range(self, start_dt, end_dt, parse_datetime, max_rows):
        if not self.timestamp_column:
            return 0

        start_value = self._query_timestamp(start_dt)
        end_value = self._query_timestamp(end_dt)
        timestamp_col = self.table.c[self.timestamp_column]

        with self.engine.connect() as connection:
            statement = select(func.count()).select_from(self.table).where(timestamp_col >= start_value).where(timestamp_col <= end_value)
            count = connection.execute(statement).scalar() or 0
        return min(int(count), int(max_rows))

    def _rows_for_range(self, start_dt, end_dt, max_rows):
        start_value = self._query_timestamp(start_dt)
        end_value = self._query_timestamp(end_dt)
        timestamp_col = self.table.c[self.timestamp_column]

        with self.engine.connect() as connection:
            statement = (
                select(self.table)
                .where(timestamp_col >= start_value)
                .where(timestamp_col <= end_value)
                .order_by(timestamp_col.asc())
                .limit(max_rows)
            )
            return connection.execute(statement).mappings().all()

    def _query_timestamp(self, value):
        timestamp_type = str(self.timestamp_column_type or 'datetime').lower()
        if timestamp_type in ('string', 'text', 'json_text', 'json_string'):
            if isinstance(value, datetime.datetime):
                return value.isoformat()
            return str(value)
        if isinstance(value, datetime.datetime) and value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value

    def _row_to_entry(self, row, fallback_id=0):
        entry = _decode_payload(row.get(self.payload_column)) if self.payload_column else None
        if entry is None:
            entry = {}
            for column_name, spec in self.columns.items():
                if column_name not in row:
                    continue
                set_source_value(entry, spec.get('source'), row.get(column_name))

        if self.id_column and self.id_column in row:
            entry['_id'] = row.get(self.id_column)
        else:
            entry['_id'] = fallback_id

        if not entry.get('timestamp') and self.timestamp_column and self.timestamp_column in row:
            entry['timestamp'] = _json_safe(row.get(self.timestamp_column))
        if not entry.get('trace_id') and self.trace_column and self.trace_column in row:
            entry['trace_id'] = row.get(self.trace_column)
        return _json_safe(entry)


def create_log_store(log_storage, log_file=None, db_config=None):
    storage = (log_storage or 'file').lower()
    if storage == 'file':
        return FileLogStore(log_file)
    if storage == 'db':
        return SQLAlchemyLogStore(db_config)
    raise ValueError("log_storage must be either 'file' or 'db'.")
