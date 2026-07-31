import uuid
from flask import g


def trace_request(request):
    trace_id = str(uuid.uuid4())
    g.trace_id = trace_id
