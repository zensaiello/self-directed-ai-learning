import time
import random
import requests
from flask import Flask, jsonify

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from prometheus_flask_exporter import PrometheusMetrics

# --- OpenTelemetry Setup ---

resource = Resource(attributes={
    "service.name": "order-api",
    "service.version": "1.0.0",
    "deployment.environment": "lab"
})

exporter = OTLPSpanExporter(
    endpoint="http://alloy:4318/v1/traces"
)

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("order-api")

# --- Flask App ---

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
metrics = PrometheusMetrics(app, group_by='endpoint')

# Custom metrics
metrics.info("order_api_info", "Order API information", version="1.0.0")


def simulate_db_query(query_name, min_ms=10, max_ms=50):
    with tracer.start_as_current_span(f"db.query.{query_name}") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", query_name)
        duration = random.uniform(min_ms, max_ms) / 1000
        time.sleep(duration)
        span.set_attribute("db.rows_returned", random.randint(1, 100))


def simulate_external_call(service_name, min_ms=20, max_ms=200):
    with tracer.start_as_current_span(f"external.{service_name}") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("peer.service", service_name)
        duration = random.uniform(min_ms, max_ms) / 1000
        time.sleep(duration)
        if random.random() < 0.1:
            time.sleep(0.5)
            span.set_attribute("slow_call", True)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/orders", methods=["GET"])
def list_orders():
    with tracer.start_as_current_span("list-orders") as span:
        span.set_attribute("endpoint", "/orders")
        simulate_db_query("select_orders", min_ms=15, max_ms=60)
        orders = [{"id": i, "status": "complete"} for i in range(1, 6)]
        span.set_attribute("orders.count", len(orders))
        return jsonify(orders)


@app.route("/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    with tracer.start_as_current_span("get-order") as span:
        span.set_attribute("order.id", order_id)
        simulate_db_query("select_order_by_id", min_ms=10, max_ms=40)
        simulate_db_query("select_inventory", min_ms=5, max_ms=25)
        simulate_external_call("pricing-service", min_ms=30, max_ms=100)
        order = {
            "id": order_id,
            "status": "complete",
            "items": random.randint(1, 5),
            "total": round(random.uniform(10.0, 500.0), 2)
        }
        span.set_attribute("order.total", order["total"])
        span.set_attribute("order.items", order["items"])
        return jsonify(order)


@app.route("/orders/checkout", methods=["POST"])
def checkout():
    with tracer.start_as_current_span("checkout") as span:
        simulate_db_query("select_cart", min_ms=10, max_ms=30)
        simulate_db_query("select_inventory_check", min_ms=15, max_ms=50)
        simulate_external_call("pricing-service", min_ms=20, max_ms=80)
        simulate_external_call("tax-service", min_ms=15, max_ms=300)
        simulate_external_call("payment-service", min_ms=50, max_ms=150)
        simulate_db_query("insert_order", min_ms=20, max_ms=60)
        total = round(random.uniform(10.0, 500.0), 2)
        span.set_attribute("checkout.total", total)
        span.set_attribute("checkout.success", True)
        return jsonify({"status": "success", "total": total})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
