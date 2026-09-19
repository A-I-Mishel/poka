/**
 * k6 Load Test Scenarios for Pluto Smart Task Agent
 *
 * Run:
 *   k6 run load-test/k6-scenarios.js
 *
 * Or with options:
 *   k6 run --vus 50 --duration 5m load-test/k6-scenarios.js
 *   k6 run --out influxdb=http://localhost:8086/k6 load-test/k6-scenarios.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';
import { randomString, randomItem } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// --- Custom Metrics ---
const errorRate = new Rate('errors');
const chatLatency = new Trend('chat_latency');
const uploadLatency = new Trend('upload_latency');
const sseLatency = new Trend('sse_latency');
const kbSearchLatency = new Trend('kb_search_latency');
const totalRequests = new Counter('total_requests');

// --- Configuration ---
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = parseInt(__ENV.VUS) || 50;
const DURATION = __ENV.DURATION || '5m';
const RAMP_UP = __ENV.RAMP_UP || '1m';
const RAMP_DOWN = __ENV.RAMP_DOWN || '30s';

// Test data
const MINIMAL_PDF = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 12 Tf 10 100 Td (k6 load test document) Tj ET
endstream
endobj
trailer<</Root 1 0 R>>
startxref
0
%%EOF`;

const SAMPLE_QUERIES = [
    'What is machine learning?',
    'Explain quantum computing',
    'How does blockchain work?',
    'What is the capital of France?',
    'Summarize the theory of relativity',
    'What are neural networks?',
    'How does photosynthesis work?',
    'What is climate change?',
    'Explain CRISPR gene editing',
    'What is the stock market?',
];

const DEEP_QUERIES = [
    'Create a presentation about renewable energy',
    'Research the impact of AI on healthcare',
    'Write a business plan for a SaaS startup',
    'Analyze the 2024 tech trends',
    'Create a project plan for mobile app development',
];

const KB_QUERIES = [
    'k6 load test document',
    'machine learning basics',
    'quantum computing explained',
    'blockchain technology',
    'neural network architecture',
];

const HEADERS = {
    'Content-Type': 'application/json',
    'X-Pluto-Visitor': `k6_user_${__VU}`,
};

// --- Helper Functions ---

function randomQuery() {
    return randomItem(SAMPLE_QUERIES);
}

function deepQuery() {
    return randomItem(DEEP_QUERIES);
}

function kbQuery() {
    return randomItem(KB_QUERIES);
}

function uploadPdf() {
    const filename = `test_${randomString(8)}.pdf`;
    const data = {
        file: http.file(MINIMAL_PDF, filename, 'application/pdf'),
    };
    const res = http.post(`${BASE_URL}/api/uploads`, data, { headers: { 'X-Pluto-Visitor': `k6_user_${__VU}` } });
    if (res.status === 200) {
        return res.json().id;
    }
    return null;
}

function randomString(length = 12) {
    return Math.random().toString(36).substring(2, 2 + length);
}

// --- Scenarios ---

export const options = {
    scenarios: {
        // 40% - Simple chat
        simple_chat: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.4) },
                { duration: '4m', target: Math.floor(VUS * 0.4) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'simple_chat' },
        },
        // 15% - Deep mode
        deep_mode: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.15) },
                { duration: '4m', target: Math.floor(VUS * 0.15) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'deep_mode' },
        },
        // 15% - File upload + KB search
        upload_kb_search: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.15) },
                { duration: '4m', target: Math.floor(VUS * 0.15) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'upload_kb_search' },
        },
        // 10% - File upload + download
        upload_download: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.1) },
                { duration: '4m', target: Math.floor(VUS * 0.1) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'upload_download' },
        },
        // 10% - SSE streaming
        sse_stream: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.1) },
                { duration: '4m', target: Math.floor(VUS * 0.1) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'sse_stream' },
        },
        // 10% - KB search only
        kb_search: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(VUS * 0.1) },
                { duration: '4m', target: Math.floor(VUS * 0.1) },
                { duration: '30s', target: 0 },
            ],
            gracefulRampDown: '30s',
            tags: { scenario: 'kb_search' },
        },
    },
    thresholds: {
        // Global SLOs
        'http_req_duration{scenario:simple_chat}': ['p(95)<3000'],
        'http_req_duration{scenario:deep_mode}': ['p(95)<15000'],
        'http_req_duration{scenario:upload_kb_search}': ['p(95)<10000'],
        'http_req_duration{scenario:upload_download}': ['p(95)<5000'],
        'http_req_duration{scenario:sse_stream}': ['p(95)<30000'],
        'http_req_duration{scenario:kb_search}': ['p(95)<5000'],

        // Error rate < 1%
        'http_req_failed': ['rate<0.01'],

        // Custom metrics
        'chat_latency': ['p(95)<5000'],
        'sse_latency': ['p(95)<30000'],
    },
    // Export to InfluxDB if configured
    ext: {
        loadimpact: {
            projectID: __ENV.K6_PROJECT_ID,
            name: 'Pluto Load Test',
        },
    },
};

// --- Main Test Function ---

export default function () {
    const scenario = __ITER.scenario || 'unknown';

    switch (scenario) {
        case 'simple_chat':
            simpleChat();
            break;
        case 'deep_mode':
            deepMode();
            break;
        case 'upload_kb_search':
            uploadKbSearch();
            break;
        case 'upload_download':
            uploadDownload();
            break;
        case 'sse_stream':
            sseStream();
            break;
        case 'kb_search':
            kbSearch();
            break;
    }

    // Think time
    sleep(Math.random() * 4 + 1);
}

// --- Scenario Implementations ---

function simpleChat() {
    group('Simple Chat', () => {
        const query = randomItem(SAMPLE_QUERIES);
        const start = new Date();

        const res = http.post(`${BASE_URL}/api/chat/send`, JSON.stringify({
            content: query,
            deep_mode: false,
            force_search: false,
        }), {
            headers: HEADERS,
            timeout: '30s',
        });

        const latency = new Date() - start;
        chatLatency.add(latency);
        totalRequests.add(1);

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'has response': (r) => r.json().message?.content?.length > 0,
            'latency < 3s': () => latency < 3000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

function deepMode() {
    group('Deep Mode', () => {
        const query = randomItem(DEEP_QUERIES);
        const start = new Date();

        const res = http.post(`${BASE_URL}/api/chat/send`, JSON.stringify({
            content: query,
            deep_mode: true,
            force_search: true,
        }), {
            headers: HEADERS,
            timeout: '120s',
        });

        const latency = new Date() - start;
        chatLatency.add(latency);
        totalRequests.add(1);

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'has response': (r) => r.json().message?.content?.length > 0,
            'latency < 15s': () => latency < 15000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

function uploadKbSearch() {
    group('Upload + KB Search', () => {
        // Upload PDF
        const uploadId = uploadPdf();
        if (!uploadId) {
            errorRate.add(true);
            return;
        }

        // Wait for KB ingest
        sleep(2);

        // Search KB
        const query = randomItem(KB_QUERIES);
        const start = new Date();

        const res = http.post(`${BASE_URL}/api/chat/send`, JSON.stringify({
            content: `Search my documents for: ${query}`,
            deep_mode: false,
            force_search: true,
        }), {
            headers: HEADERS,
            timeout: '30s',
        });

        const latency = new Date() - start;
        kbSearchLatency.add(latency);
        totalRequests.add(1);

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'has response': (r) => r.json().message?.content?.length > 0,
            'latency < 10s': () => latency < 10000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

function uploadDownload() {
    group('Upload + Download', () => {
        // Upload
        const uploadId = uploadPdf();
        if (!uploadId) {
            errorRate.add(true);
            return;
        }

        // Download
        const start = new Date();
        const res = http.get(`${BASE_URL}/api/uploads/${uploadId}/file`, {
            headers: { 'X-Pluto-Visitor': `k6_user_${__VU}` },
        });

        const latency = new Date() - start;
        uploadLatency.add(latency);
        totalRequests.add(1);

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'content length > 100': (r) => r.body.length > 100,
            'latency < 5s': () => latency < 5000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

function sseStream() {
    group('SSE Streaming', () => {
        const query = randomItem(SAMPLE_QUERIES);
        const start = new Date();

        // SSE is a streaming response - we need to handle it differently
        const res = http.post(`${BASE_URL}/api/chat/stream`, JSON.stringify({
            content: query,
            deep_mode: false,
        }), {
            headers: { ...HEADERS, 'Accept': 'text/event-stream' },
            timeout: '60s',
        });

        const latency = new Date() - start;
        sseLatency.add(latency);
        totalRequests.add(1);

        // Parse SSE events
        let eventsReceived = 0;
        let doneReceived = false;

        if (res.status === 200 && res.body) {
            const lines = res.body.split('\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    eventsReceived++;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'done') {
                            doneReceived = true;
                            break;
                        } else if (data.type === 'error') {
                            // Error in stream
                            break;
                        }
                    } catch (e) {
                        // Ignore parse errors
                    }
                }
            }
        }

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'events received': () => eventsReceived > 2,
            'done received': () => doneReceived,
            'latency < 30s': () => latency < 30000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

function kbSearch() {
    group('KB Search', () => {
        const query = randomItem(KB_QUERIES);
        const start = new Date();

        const res = http.post(`${BASE_URL}/api/chat/send`, JSON.stringify({
            content: `Search my knowledge base for: ${query}`,
            deep_mode: false,
            force_search: true,
        }), {
            headers: HEADERS,
            timeout: '30s',
        });

        const latency = new Date() - start;
        kbSearchLatency.add(latency);
        totalRequests.add(1);

        const success = check(res, {
            'status 200': (r) => r.status === 200,
            'has response': (r) => r.json().message?.content?.length > 0,
            'latency < 5s': () => latency < 5000,
        });

        errorRate.add(!success);
        sleep(Math.random() * 4 + 1);
    }
}

// --- Setup/Teardown ---

export function setup() {
    console.log(`Starting load test against ${BASE_URL}`);
    console.log(`Target VUs: ${VUS}, Duration: ${DURATION}`);

    // Health check
    const res = http.get(`${BASE_URL}/api/health`, { timeout: '10s' });
    if (res.status !== 200) {
        throw new Error(`Health check failed: ${res.status}`);
    }
    console.log('Health check passed');

    return { baseUrl: BASE_URL };
}

export function teardown(data) {
    console.log('Load test completed');
    console.log(`Total requests: ${totalRequests.values.count}`);
    console.log(`Error rate: ${(errorRate.values.passes / (errorRate.values.passes + errorRate.values.fails) * 100).toFixed(2)}%`);
}
