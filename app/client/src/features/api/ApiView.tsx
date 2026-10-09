// API view (integration engineers): endpoints, copy-ready curl examples, links to the OpenAPI docs.

import { useFeedback } from "../../components/feedback";
import { API_BASE, apiUrl } from "../../lib/api";
import { Button, Card, PanelHead } from "../../components/ui";

const ENDPOINTS: [method: "GET" | "POST" | "DELETE", path: string, key: boolean, what: string][] = [
  ["GET", "/health", false, "Readiness and model version. 503 while the model loads."],
  ["POST", "/predict", true, "Classify one ticket."],
  ["POST", "/predict/batch", true, "Classify 1–100 tickets, results in the same order."],
  ["POST", "/batch/jobs", true, "Start a background job for 1–5,000 tickets (202 + job_id)."],
  ["GET", "/batch/jobs/{id}", true, "Job status and progress."],
  ["GET", "/batch/jobs/{id}/results", true, "Results in request order, paged with offset and limit."],
  ["DELETE", "/batch/jobs/{id}", true, "Cancel a running job or discard a finished one."],
];

const METHOD_TONE = { GET: "bg-success-soft text-success", POST: "bg-accent-soft text-accent", DELETE: "bg-danger-soft text-danger" } as const;

export function ApiView() {
  const { toast } = useFeedback();
  // The API lives on its own host; in dev (proxy) it shares this page's origin.
  const base = API_BASE || window.location.origin;
  const examples: [string, string][] = [
    ["Check health (no key)", `curl -s ${base}/health`],
    [
      "Classify one ticket",
      `curl -s -X POST ${base}/predict \\\n  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \\\n  -d '{"channel": "chat", "text": "bro mage order eka late, refund ekak denna"}'`,
    ],
    [
      "Classify up to 100 tickets",
      `curl -s -X POST ${base}/predict/batch \\\n  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \\\n  -d '{"tickets": [{"ticket_id": "T-1", "channel": "email", "subject": "Refund", "text": "I was charged twice."}]}'`,
    ],
    [
      "Start a background job (up to 5,000)",
      `curl -s -i -X POST ${base}/batch/jobs \\\n  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \\\n  -d @tickets.json        # {"tickets": [...]}`,
    ],
    [
      "Follow the job, then fetch results",
      `curl -s ${base}/batch/jobs/$JOB_ID -H "X-API-Key: $API_KEY"\ncurl -s "${base}/batch/jobs/$JOB_ID/results?offset=0&limit=1000" -H "X-API-Key: $API_KEY"`,
    ],
  ];

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied to clipboard");
    } catch {
      toast("Copy failed. Select the text and copy it manually.");
    }
  };

  return (
    <>
      <PanelHead title="API for integrations">
        Everything this page does goes through the public API at <code>{base}</code>, so a helpdesk can call the same endpoints directly. Send the key as <code>X-API-Key: &lt;key&gt;</code> or{" "}
        <code>Authorization: Bearer &lt;key&gt;</code>. <code>/health</code> needs no key.
      </PanelHead>
      <Card>
        <div className="mb-4 flex flex-wrap gap-2">
          {(
            [
              ["/docs", "Interactive docs (Swagger)"],
              ["/redoc", "Reference (ReDoc)"],
              ["/openapi.json", "openapi.json"],
            ] as const
          ).map(([href, label]) => (
            <a key={href} href={apiUrl(href)} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center rounded-md border border-border-strong bg-surface px-4 py-2 font-semibold text-text no-underline hover:bg-surface-2">
              {label} <span aria-hidden="true">&nbsp;↗</span>
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ))}
        </div>
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Endpoints</caption>
            <thead>
              <tr>
                {["Method", "Path", "Key", "What it does"].map((h) => (
                  <th key={h} scope="col" className="border-b border-border bg-surface-2 px-3 py-2 text-left text-[13px] font-semibold text-text-2">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ENDPOINTS.map(([method, path, key, what]) => (
                <tr key={method + path} className="border-b border-border last:border-b-0">
                  <td className="px-3 py-2">
                    <span className={`rounded px-1.5 py-0.5 font-mono text-xs font-bold ${METHOD_TONE[method]}`}>{method}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono">{path}</td>
                  <td className="px-3 py-2">{key ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {examples.map(([title, code]) => (
        <Card key={title}>
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">{title}</h2>
            <Button size="sm" onClick={() => void copy(code)}>Copy</Button>
          </div>
          <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-surface-2 p-3 font-mono text-[13px] leading-normal">{code}</pre>
        </Card>
      ))}
    </>
  );
}
