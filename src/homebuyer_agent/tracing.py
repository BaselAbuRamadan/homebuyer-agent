"""Tracing: send a record of every agent step to the local Arize Phoenix server.

Two words to know:
- span:  one step, e.g. "route() ran" or "one OpenAI call". It has a start, an end,
         inputs, outputs and labels (attributes).
- trace: all spans for ONE request, nested as a tree, e.g.
         eval_case R10 -> route -> OpenAI call.

Call setup_tracing() once at the start of a script. Until it is called, every
span in the code is a cheap "no-op", so tracing is entirely optional.
"""
import os
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

from openinference.semconv.trace import SpanAttributes
from opentelemetry import trace

# Phoenix itself is imported inside setup_tracing(), not here. Code that never turns
# tracing on (like the public web app) then doesn't need the large Phoenix package.

PROJECT_NAME = "homebuyer-agent"


def get_tracer() -> trace.Tracer:
    """Return the tracer our own code uses to create custom spans (route, eval_case, ...)."""
    return trace.get_tracer("homebuyer_agent")


@contextmanager
def traced_step(name: str, kind: str, input_value: str | None = None) -> Iterator[trace.Span]:
    """Shortcut for one custom span: `with traced_step("retrieve", "RETRIEVER", query) as span:`.

    kind is the OpenInference span kind Phoenix uses for the icon/colour:
    CHAIN (a step of our own logic), RETRIEVER (search), TOOL (a tool call), AGENT (the whole run).
    """
    with get_tracer().start_as_current_span(name) as span:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind)
        if input_value is not None:
            span.set_attribute(SpanAttributes.INPUT_VALUE, input_value)
        yield span


def set_output(span: trace.Span, value: str) -> None:
    """Record what a step produced, shown as 'Output' in Phoenix."""
    span.set_attribute(SpanAttributes.OUTPUT_VALUE, value)


def setup_tracing() -> None:
    """Connect to Phoenix and start recording every OpenAI call automatically.

    - register() creates the tracer provider: the part that collects spans and sends
      them to Phoenix's /v1/traces endpoint under our project name.
    - OpenAIInstrumentor patches the openai SDK so each API call becomes a span
      holding the exact messages sent, the reply, latency and token counts.
    """
    from openinference.instrumentation.openai import OpenAIInstrumentor   # only needed when tracing
    from phoenix.otel import register

    base_url = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006").rstrip("/")
    try:
        urllib.request.urlopen(base_url, timeout=3)
    except Exception:
        print(f"⚠️  Phoenix is not reachable at {base_url}. Start it with: phoenix serve")
        print("    The run will continue, but no traces will be recorded.\n")

    tracer_provider = register(
        endpoint=f"{base_url}/v1/traces",
        project_name=PROJECT_NAME,
        batch=False,     # send each span immediately: simpler, and nothing is lost when a short script exits
        verbose=False,
    )
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    print(f"🔭 Tracing on: open {base_url} → project '{PROJECT_NAME}'\n")
