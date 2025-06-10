import uuid
from flask import g

def trace_request(request):
    # Generate a trace ID
    trace_id = str(uuid.uuid4())
    g.trace_id = trace_id
    print(f"Trace ID: {trace_id} for {request.method} {request.path}")
