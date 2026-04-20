import { useEffect, useRef, useState, useCallback } from "react";
import { getBridge, type Bridge } from "./bridge";

type Row =
  | { kind: "system"; text: string }
  | { kind: "user";   text: string }
  | { kind: "error";  text: string }
  | { kind: "assistant"; id: string; text: string; done: boolean }
  | { kind: "tool"; id: string; name: string; input: string; result?: string; isError?: boolean; done: boolean }
  | { kind: "permission"; reqId: string; name: string; input: string; decided: "pending" | "applied" | "rejected" };

let rowSeq = 0;
const nextId = () => `r${++rowSeq}`;
const short = (n: string) => (n.startsWith("mcp__cad__") ? n.slice(10) : n);

function previewResult(json: string): string {
  try {
    const c = JSON.parse(json);
    if (Array.isArray(c) && c[0]?.text) return c[0].text;
    return JSON.stringify(c, null, 2);
  } catch { return json; }
}
function prettyInput(json: string): string {
  try { return JSON.stringify(JSON.parse(json), null, 2); } catch { return json; }
}

export function App() {
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [bypass, setBypass] = useState(false);
  const [text, setText] = useState("");
  const bridgeRef = useRef<Bridge | null>(null);
  const streamRef = useRef<HTMLDivElement>(null);
  const assistantIdRef = useRef<string | null>(null);

  const push = useCallback((r: Row) => setRows((xs) => [...xs, r]), []);
  const patch = useCallback(
    (pred: (r: Row) => boolean, update: (r: Row) => Row) =>
      setRows((xs) => xs.map((r) => (pred(r) ? update(r) : r))),
    [],
  );

  useEffect(() => {
    let alive = true;
    getBridge().then((bridge) => {
      if (!alive) return;
      bridgeRef.current = bridge;

      bridge.assistantText.connect((t) => {
        const id = assistantIdRef.current;
        if (id) {
          patch((r) => r.kind === "assistant" && r.id === id,
                (r) => ({ ...(r as Row & { kind: "assistant" }), text: (r as any).text + t }));
        } else {
          const newId = nextId();
          assistantIdRef.current = newId;
          push({ kind: "assistant", id: newId, text: t, done: false });
        }
      });

      bridge.toolUse.connect((id, name, input) => {
        assistantIdRef.current = null;
        push({ kind: "tool", id, name, input, done: false });
      });
      bridge.toolResult.connect((id, content, isError) => {
        patch((r) => r.kind === "tool" && r.id === id,
              (r) => ({ ...(r as any), result: content, isError, done: true }));
      });
      bridge.permissionRequest.connect((reqId, name, input) => {
        assistantIdRef.current = null;
        push({ kind: "permission", reqId, name, input, decided: "pending" });
      });
      bridge.turnComplete.connect((cost) => {
        const id = assistantIdRef.current;
        if (id) patch((r) => r.kind === "assistant" && r.id === id,
                      (r) => ({ ...(r as any), done: true }));
        assistantIdRef.current = null;
        if (cost >= 0) push({ kind: "system", text: `turn complete · $${cost.toFixed(4)}` });
        setBusy(false);
      });
      bridge.errorText.connect((t) => push({ kind: "error", text: t }));
      bridge.systemText.connect((t) => push({ kind: "system", text: t }));
      bridge.bypassChanged.connect((on) => setBypass(on));

      push({ kind: "system", text: "CAD Agent ready. Ask me to model something." });
    });
    return () => { alive = false; };
  }, [push, patch]);

  useEffect(() => {
    streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight });
  }, [rows]);

  const doSend = () => {
    const t = text.trim();
    if (!t || !bridgeRef.current) return;
    push({ kind: "user", text: t });
    setText("");
    setBusy(true);
    bridgeRef.current.submit(t);
  };
  const doStop = () => bridgeRef.current?.stop();
  const decide = (reqId: string, allowed: boolean) => {
    bridgeRef.current?.decidePermission(
      reqId, allowed, allowed ? "" : "User rejected this action.",
    );
    patch((r) => r.kind === "permission" && r.reqId === reqId,
          (r) => ({ ...(r as any), decided: allowed ? "applied" : "rejected" }));
  };

  return (
    <div className="app">
      <div className="stream" ref={streamRef}>
        {rows.map((r, i) => <RowView key={i} row={r} decide={decide} />)}
      </div>
      <div className="composer">
        <div className="composer-frame">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault(); doSend();
              }
            }}
            placeholder="Ask the CAD agent…"
            rows={1}
          />
          <div className="toolbar">
            <button className="pill" title="Attach">+</button>
            <button className="pill" title="Commands">⁄</button>
            <span className="chip">▤&nbsp;&nbsp;CAD Agent</span>
            <div style={{ flex: 1 }} />
            {bypass && <span className="perm">⛨&nbsp;&nbsp;Bypass permissions</span>}
            {busy
              ? <button className="stop" onClick={doStop} title="Stop">■</button>
              : <button className="send" onClick={doSend} title="Send (Ctrl+Enter)">↑</button>}
          </div>
        </div>
      </div>
    </div>
  );
}

function RowView({ row, decide }: { row: Row; decide: (reqId: string, allowed: boolean) => void }) {
  switch (row.kind) {
    case "system":    return <div className="system">{row.text}</div>;
    case "user":      return <div className="user">{row.text}</div>;
    case "error":     return (
      <div className="row">
        <span className="dot error" />
        <span className="err-text">{row.text}</span>
      </div>
    );
    case "assistant": return (
      <div className="row">
        <span className={`dot ${row.done ? "done" : "active"}`} />
        <div style={{ whiteSpace: "pre-wrap", flex: 1 }}>{row.text}</div>
      </div>
    );
    case "tool": {
      const state = row.done ? (row.isError ? "error" : "done") : "pending";
      return (
        <div className="row">
          <span className={`dot ${state}`} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div><span className="tool-title">{short(row.name)}</span></div>
            <div><span className="badge">IN</span><pre className="code">{prettyInput(row.input)}</pre></div>
            {row.result !== undefined && (
              <div>
                <span className="badge">{row.isError ? "ERR" : "OUT"}</span>
                <pre className="code" style={row.isError ? { color: "var(--err)" } : undefined}>
                  {previewResult(row.result).slice(0, 2000)}
                </pre>
              </div>
            )}
          </div>
        </div>
      );
    }
    case "permission": {
      const state = row.decided === "pending" ? "active"
                 : row.decided === "applied" ? "done" : "error";
      return (
        <div className="row card">
          <span className={`dot ${state}`} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div>
              <span className="tool-title">{short(row.name)}</span>
              <span className="pending-chip">pending approval</span>
            </div>
            <pre className="code">{prettyInput(row.input)}</pre>
            <div className="actions">
              <button className="reject" disabled={row.decided !== "pending"}
                      onClick={() => decide(row.reqId, false)}>Reject</button>
              <button className="apply"  disabled={row.decided !== "pending"}
                      onClick={() => decide(row.reqId, true)}>Apply</button>
            </div>
          </div>
        </div>
      );
    }
  }
}
