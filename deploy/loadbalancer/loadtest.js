// Load test for the balanced stack, using k6 (free, open source). A realistic mix of PUBLIC pages (what most visitors request).
//
//   docker run --rm -i --network lenden-saathi-lb_default -e BASE_URL=http://haproxy -e VUS=50 \
//       -v "%cd%/loadtest.js:/script.js" grafana/k6 run /script.js
//
// Before running it, raise the per-address limit so the balancer does not (rightly) block your single test machine:
//   RATE_PER_10S=1000000 docker compose -f docker-compose.yml -f docker-compose.localdb.yml up -d --scale app=4
// Compare capacity by running it once with --scale app=1 and again with --scale app=4.
import http from 'k6/http';
import { check, sleep } from 'k6';

const VUS = parseInt(__ENV.VUS || '50');

export const options = {
  stages: [
    { duration: '15s', target: VUS },
    { duration: '45s', target: VUS },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],      // fewer than 1% errors
    http_req_duration: ['p(95)<800'],    // 95% of requests answered within 0.8 s
  },
};

const BASE = __ENV.BASE_URL || 'http://haproxy';
const HEADERS = { headers: { Host: 'localhost' } };

export default function () {
  const r = Math.random();
  let path = '/';                         // the home page: most traffic
  if (r > 0.55 && r <= 0.70) path = '/pricing/';
  else if (r > 0.70 && r <= 0.82) path = '/faq/';
  else if (r > 0.82 && r <= 0.90) path = '/features/';
  else if (r > 0.90 && r <= 0.95) path = '/how-it-works/';
  else if (r > 0.95) path = '/health/live';
  const res = http.get(BASE + path, HEADERS);
  check(res, { 'status is 200': (x) => x.status === 200 });
  sleep(0.05);
}
