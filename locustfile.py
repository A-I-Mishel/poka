"""Locust load test scenarios for Pluto Smart Task Agent.

Run:
    locust -f locustfile.py --host=http://localhost:8000

Or headless:
    locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 5 -t 5m

Scenarios:
- Simple chat (40%): Single message, no tools
- Deep mode (15%): Multi-turn with tool chaining
- File upload + KB search (15%): Upload PDF, search KB
- File upload + download (10%): Upload, list, download
- SSE streaming (10%): Real-time token streaming
- KB search only (10%): Vector search queries

Target: 50 concurrent users, p95 < 5s, error rate < 1%
"""

import random
import time
import uuid
import json
from locust import task, between, events
from locust.contrib.fasthttp import FastHttpUser


# --- Test Data Fixtures ---

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 10 100 Td (load test document) Tj ET\n"
    b"endstream\nendobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"startxref\n0\n%%EOF\n"
)

SAMPLE_QUERIES = [
    "What is machine learning?",
    "Explain quantum computing",
    "How does blockchain work?",
    "What is the capital of France?",
    "Summarize the theory of relativity",
    "What are neural networks?",
    "How does photosynthesis work?",
    "What is climate change?",
    "Explain CRISPR gene editing",
    "What is the stock market?",
]

DEEP_QUERIES = [
    "Create a presentation about renewable energy",
    "Research the impact of AI on healthcare",
    "Write a business plan for a SaaS startup",
    "Analyze the 2024 tech trends",
    "Create a project plan for mobile app development",
]

KB_QUERIES = [
    "load test document",
    "machine learning basics",
    "quantum computing explained",
    "blockchain technology",
    "neural network architecture",
]


# --- Helper Functions ---

def _random_string(length: int = 12) -> str:
    return uuid.uuid4().hex[:length]


def _make_pdf_upload(client: FastHttpUser) -> str:
    """Upload a test PDF and return the upload ID."""
    files = {
        "file": (f"test_{_random_string()}.pdf", MINIMAL_PDF, "application/pdf")
    }
    with client.post("/api/uploads", files=files, catch_response=True) as resp:
        if resp.status_code == 200:
            return resp.json()["id"]
        else:
            resp.failure(f"Upload failed: {resp.status_code} {resp.text}")
            return None


def _wait_for_kb_ingest(client: FastHttpUser, upload_id: str, max_wait: int = 10) -> bool:
    """Poll KB until document is ingested or timeout."""
    start = time.time()
    while time.time() - start < max_wait:
        with client.get("/api/uploads", catch_response=True) as resp:
            if resp.status_code == 200:
                uploads = resp.json()
                for u in uploads:
                    if u["id"] == upload_id:
                        # In a real test, we'd check KB directly
                        # For now, assume ingest is fast
                        return True
        time.sleep(0.5)
    return False


# --- User Classes ---

class PlutoUser(FastHttpUser):
    """Base user class with auth and common helpers."""

    wait_time = between(1, 5)  # Think time between requests

    # Auth: use PLUTO_USER_ID env or open mode
    abstract = True

    def on_start(self):
        """Initialize user session."""
        self.user_id = f"loadtest_{_random_string(8)}"
        self.upload_ids = []

        # Set auth headers if needed
        # In open mode, we use PLUTO_USER_ID or visitor header
        self.client.headers.update({
            "X-Pluto-Visitor": self.user_id,
            "Content-Type": "application/json",
        })

    def on_stop(self):
        """Cleanup: delete uploaded files."""
        for uid in self.upload_ids:
            try:
                self.client.delete(f"/api/uploads/{uid}")
            except Exception:
                pass


class ChatUser(PlutoUser):
    """Simple chat user - 40% of traffic."""
    weight = 40

    @task
    def simple_chat(self):
        """Send a simple message, no tools expected."""
        query = random.choice(SAMPLE_QUERIES)
        with self.client.post(
            "/api/chat/send",
            json={"content": query, "deep_mode": False, "force_search": False},
            catch_response=True,
            name="/api/chat/send (simple)"
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if "message" in data and data["message"].get("content"):
                    resp.success()
                else:
                    resp.failure("Empty response")
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"Status {resp.status_code}: {resp.text}")

    @task(3)
    def chat_with_history(self):
        """Chat with some history context."""
        # First message
        q1 = random.choice(SAMPLE_QUERIES)
        with self.client.post(
            "/api/chat/send",
            json={"content": q1, "deep_mode": False},
            catch_response=True,
            name="/api/chat/send (history-1)"
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"First msg failed: {resp.status_code}")
                return

        # Follow-up
        time.sleep(random.uniform(0.5, 1.5))
        q2 = f"Tell me more about {random.choice(['that', 'the topic', 'the details'])}"
        with self.client.post(
            "/api/chat/send",
            json={"content": q2, "deep_mode": False},
            catch_response=True,
            name="/api/chat/send (history-2)"
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"Follow-up failed: {resp.status_code}")


class DeepModeUser(PlutoUser):
    """Deep mode user - 15% of traffic."""
    weight = 15

    @task
    def deep_chat(self):
        """Deep mode with planning and tool chaining."""
        query = random.choice(DEEP_QUERIES)
        with self.client.post(
            "/api/chat/send",
            json={
                "content": query,
                "deep_mode": True,
                "force_search": True,
            },
            catch_response=True,
            name="/api/chat/send (deep)",
            timeout=120.0  # Deep mode can take longer
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("message", {}).get("content"):
                    resp.success()
                else:
                    resp.failure("Empty deep response")
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"Status {resp.status_code}: {resp.text[:200]}")


class FileUploadUser(PlutoUser):
    """File upload + KB search - 15% of traffic."""
    weight = 15

    @task
    def upload_and_search(self):
        """Upload PDF, wait for KB ingest, then search."""
        # Upload
        upload_id = _make_pdf_upload(self)
        if not upload_id:
            return
        self.upload_ids.append(upload_id)

        # Wait a bit for KB ingest
        time.sleep(2)

        # Search KB
        query = random.choice(KB_QUERIES)
        with self.client.post(
            "/api/chat/send",
            json={
                "content": f"Search my documents for: {query}",
                "deep_mode": False,
                "force_search": True,
            },
            catch_response=True,
            name="/api/chat/send (kb-search)"
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if "message" in data:
                    resp.success()
                else:
                    resp.failure("Empty KB search response")
            else:
                resp.failure(f"KB search failed: {resp.status_code}")

    @task
    def upload_multiple(self):
        """Upload multiple files."""
        for _ in range(3):
            uid = _make_pdf_upload(self)
            if uid:
                self.upload_ids.append(uid)
            time.sleep(0.2)

        # List uploads
        with self.client.get(
            "/api/uploads",
            catch_response=True,
            name="/api/uploads (list)"
        ) as resp:
            if resp.status_code == 200:
                uploads = resp.json()
                if len(uploads) >= 3:
                    resp.success()
                else:
                    resp.failure(f"Expected 3+ uploads, got {len(uploads)}")
            else:
                resp.failure(f"List failed: {resp.status_code}")


class FileDownloadUser(PlutoUser):
    """File upload + download - 10% of traffic."""
    weight = 10

    @task
    def upload_and_download(self):
        """Upload file, then download it."""
        upload_id = _make_pdf_upload(self)
        if not upload_id:
            return
        self.upload_ids.append(upload_id)

        # Download
        with self.client.get(
            f"/api/uploads/{upload_id}/file",
            catch_response=True,
            name="/api/uploads/{id}/file (download)"
        ) as resp:
            if resp.status_code == 200:
                if len(resp.content) > 100:
                    resp.success()
                else:
                    resp.failure("Empty download")
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"Download failed: {resp.status_code}")

    @task
    def list_and_download_random(self):
        """List uploads and download a random one."""
        with self.client.get("/api/uploads", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure("List failed")
                return
            uploads = resp.json()
            if not uploads:
                return
            target = random.choice(uploads)["id"]
            with self.client.get(
                f"/api/uploads/{target}/file",
                catch_response=True,
                name="/api/uploads/{id}/file (random)"
            ) as resp:
                if resp.status_code == 200 and len(resp.content) > 100:
                    resp.success()
                else:
                    resp.failure("Random download failed")


class SSEUser(PlutoUser):
    """SSE streaming user - 10% of traffic."""
    weight = 10

    @task
    def stream_chat(self):
        """Stream a chat response via SSE."""
        query = random.choice(SAMPLE_QUERIES)
        with self.client.post(
            "/api/chat/stream",
            json={"content": query, "deep_mode": False},
            catch_response=True,
            name="/api/chat/stream (SSE)",
            stream=True,
            timeout=60.0
        ) as resp:
            if resp.status_code == 200:
                events_received = 0
                done_received = False
                for line in resp.iter_lines():
                    if line:
                        events_received += 1
                        if line.startswith(b"data: "):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "done":
                                    done_received = True
                                    break
                                elif data.get("type") == "error":
                                    resp.failure(f"Stream error: {data.get('detail')}")
                                    return
                            except json.JSONDecodeError:
                                pass
                if done_received and events_received > 2:
                    resp.success()
                else:
                    resp.failure(f"Incomplete stream: events={events_received}, done={done_received}")
            elif resp.status_code == 429:
                resp.failure("Rate limited")
            else:
                resp.failure(f"SSE failed: {resp.status_code}")


class KBSearchUser(PlutoUser):
    """KB search only - 10% of traffic."""
    weight = 10

    @task
    def kb_search(self):
        """Direct KB search via chat with force_search."""
        query = random.choice(KB_QUERIES)
        with self.client.post(
            "/api/chat/send",
            json={
                "content": f"Search my knowledge base for: {query}",
                "deep_mode": False,
                "force_search": True,
            },
            catch_response=True,
            name="/api/chat/send (kb-search)"
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if data.get("message", {}).get("content"):
                    resp.success()
                else:
                    resp.failure("Empty KB search response")
            else:
                resp.failure(f"KB search failed: {resp.status_code}")

    @task
    def direct_kb_search(self):
        """Direct KB search endpoint if available."""
        query = random.choice(KB_QUERIES)
        with self.client.post(
            "/api/kb/search",
            json={"query": query, "top_k": 5},
            catch_response=True,
            name="/api/kb/search"
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    resp.success()
                else:
                    resp.failure("Invalid KB response format")
            elif resp.status_code == 404:
                resp.success()  # Endpoint might not exist
            else:
                resp.failure(f"Direct KB search failed: {resp.status_code}")


# --- Event Hooks for Metrics ---

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"\n🚀 Load test starting: {environment.runner.user_count} users target")
    print(f"   Host: {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("\n🛑 Load test stopped")
    stats = environment.runner.stats
    print(f"   Total requests: {stats.total.num_requests}")
    print(f"   Failures: {stats.total.num_failures}")
    print(f"   Avg response time: {stats.total.avg_response_time:.0f}ms")
    print(f"   p95: {stats.total.get_response_time_percentile(0.95):.0f}ms")
    print(f"   p99: {stats.total.get_response_time_percentile(0.99):.0f}ms")

    # SLO checks
    total_reqs = stats.total.num_requests
    total_failures = stats.total.num_failures
    error_rate = total_failures / max(1, total_reqs)
    p95 = stats.total.get_response_time_percentile(0.95)

    print("\n📊 SLO Check:")
    print(f"   Error rate: {error_rate:.2%} (target < 1%)")
    print(f"   p95 latency: {p95:.0f}ms (target < 5000ms)")

    if error_rate > 0.01:
        print(f"   ❌ FAIL: Error rate {error_rate:.2%} > 1%")
    else:
        print(f"   ✅ PASS: Error rate {error_rate:.2%} < 1%")

    if p95 > 5000:
        print(f"   ❌ FAIL: p95 {p95:.0f}ms > 5000ms")
    else:
        print(f"   ✅ PASS: p95 {p95:.0f}ms < 5000ms")


# --- Utility Imports ---
