import { useCallback, useEffect, useState } from "react";
import { api, ApiError, USE_MOCK, errorMessage, type HealthResponse } from "../api/client";
import { AppBar, Page } from "../components/AppBar";
import { Button, Card, SectionHeader, SkeletonLines, cx } from "../components/ui";

type Health =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "error"; message: string; unreachable: boolean };

export default function SettingsPage() {
  const [health, setHealth] = useState<Health>({ kind: "loading" });
  const [checking, setChecking] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportMsg, setExportMsg] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const check = useCallback(async (signal?: AbortSignal) => {
    setChecking(true);
    try {
      const data = await api.health({ signal, timeoutMs: 8000 });
      setHealth({ kind: "ok", data });
    } catch (e) {
      if (signal?.aborted) return;
      const unreachable = e instanceof ApiError && (e.code === "network_error" || e.code === "timeout");
      setHealth({ kind: "error", message: errorMessage(e), unreachable });
    } finally {
      if (!signal?.aborted) setChecking(false);
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    void check(ctrl.signal);
    return () => ctrl.abort();
  }, [check]);

  const doExport = async () => {
    setExporting(true);
    setExportMsg(null);
    try {
      const data = await api.exportAll();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rolo-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      const n = data.contacts.length;
      setExportMsg({ tone: "ok", text: `Exported ${n} ${n === 1 ? "contact" : "contacts"}.` });
    } catch (e) {
      setExportMsg({ tone: "error", text: `Export failed. ${errorMessage(e)}` });
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <AppBar title="Settings" back />
      <Page>
        <h1 className="text-title font-semibold">Settings</h1>

        <div className="mt-6 space-y-4">
          <Card aria-labelledby="model-h">
            <SectionHeader id="model-h">Model</SectionHeader>
            <div aria-live="polite">
              {health.kind === "loading" && (
                <div aria-busy="true">
                  <p className="text-body text-navy-500">Checking the local model…</p>
                  <SkeletonLines lines={1} className="mt-3" />
                </div>
              )}
              {health.kind === "ok" && <ModelStatus data={health.data} />}
              {health.kind === "error" && (
                <>
                  <Pill ok={false}>Rolo server not reachable</Pill>
                  <p className="mt-3 text-body">{health.message}</p>
                  <FixSteps
                    steps={
                      health.unreachable
                        ? ["On the laptop, start Rolo with ./run.sh from the project folder.", "If you're on a phone, make sure it's on the same Wi-Fi as the laptop.", "Tap Check again."]
                        : ["Restart Rolo with ./run.sh.", "Tap Check again."]
                    }
                  />
                </>
              )}
            </div>
            <Button variant="secondary" className="mt-4" onClick={() => void check()} loading={checking && health.kind !== "loading"} loadingText="Checking…" disabled={checking}>
              Check again
            </Button>
          </Card>

          <Card aria-labelledby="voice-h">
            <SectionHeader id="voice-h">Voice</SectionHeader>
            <div aria-live="polite">
              {health.kind === "loading" && <p className="text-body text-navy-500">Checking voice…</p>}
              {health.kind === "ok" && <VoiceStatus data={health.data} />}
              {health.kind === "error" && <p className="text-body text-navy-500">Voice status is unavailable until the Rolo server is reachable.</p>}
            </div>
            {!window.isSecureContext && (
              <p className="mt-3 text-body text-navy-500">
                This page isn't on the secure address, so the microphone is blocked. On a phone, open{" "}
                <span className="font-medium text-navy-900">https://{window.location.hostname}:{window.location.port || "5173"}</span>.
              </p>
            )}
          </Card>

          <Card aria-labelledby="data-h">
            <SectionHeader id="data-h">Your data</SectionHeader>
            <p className="text-body text-navy-500">Download every contact and note as a JSON file.</p>
            <Button className="mt-4 w-full sm:w-auto" onClick={() => void doExport()} loading={exporting} loadingText="Exporting…">
              Export JSON
            </Button>
            {exportMsg && (
              <p role={exportMsg.tone === "error" ? "alert" : "status"} className={cx("mt-3 text-label", exportMsg.tone === "error" ? "text-danger" : "text-success")}>
                {exportMsg.text}
              </p>
            )}
          </Card>

          <Card aria-labelledby="privacy-h">
            <SectionHeader id="privacy-h">Privacy</SectionHeader>
            <p className="text-body">Your notes never leave this device's network.</p>
          </Card>

          <Card aria-labelledby="about-h">
            <SectionHeader id="about-h">About</SectionHeader>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body">
              <dt className="text-navy-500">Version</dt>
              <dd>{__APP_VERSION__}{USE_MOCK ? " (mock data)" : ""}</dd>
            </dl>
          </Card>
        </div>
      </Page>
    </>
  );
}

function Pill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-label font-medium text-white",
        ok ? "bg-success" : "bg-danger",
      )}
    >
      <span className="size-2 rounded-full bg-white" aria-hidden="true" />
      {children}
    </span>
  );
}

function FixSteps({ steps }: { steps: string[] }) {
  return (
    <>
      <h3 className="mt-4 text-label font-medium text-navy-700">How to fix</h3>
      <ol className="mt-1 list-decimal space-y-1 pl-5 text-body">
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    </>
  );
}

function ModelStatus({ data }: { data: HealthResponse }) {
  if (!data?.model || typeof data.model.name !== "string") {
    return (
      <>
        <Pill ok={false}>Model status unknown</Pill>
        <p className="mt-3 text-body">The Rolo server answered but didn't report which model it uses.</p>
        <FixSteps steps={["Restart Rolo with ./run.sh.", "Tap Check again."]} />
      </>
    );
  }
  const { name, available, detail } = data.model;
  if (available) {
    return (
      <>
        <Pill ok>{name} running locally</Pill>
        <p className="mt-3 text-body text-navy-500">Notes are organised by this model on your own machine.</p>
      </>
    );
  }
  return (
    <>
      <Pill ok={false}>{name} not available</Pill>
      {detail && <p className="mt-3 text-body">{detail}</p>}
      <p className="mt-2 text-body text-navy-500">You can still save contacts. Enrichment will work once the model is running.</p>
      <FixSteps
        steps={[
          "Open the Ollama app on the laptop (or run: ollama serve).",
          `Make sure the model is downloaded: ollama pull ${name}`,
          "Tap Check again.",
        ]}
      />
    </>
  );
}

function VoiceStatus({ data }: { data: HealthResponse }) {
  const asr = data.asr;
  if (!asr || typeof asr.name !== "string") {
    return <p className="text-body text-navy-500">This server doesn't report voice status.</p>;
  }
  if (asr.available) {
    return (
      <>
        <Pill ok>{asr.name} running locally</Pill>
        <p className="mt-3 text-body text-navy-500">Speech is transcribed on your laptop. Audio is never stored.</p>
        <p className="mt-1 text-meta text-navy-500">Works in English and major European languages.</p>
      </>
    );
  }
  return (
    <>
      <Pill ok={false}>Voice not available</Pill>
      {asr.detail && <p className="mt-3 text-body">{asr.detail}</p>}
      <p className="mt-2 text-body text-navy-500">Typing still works.</p>
      <FixSteps steps={["On the laptop, run ./run.sh once to set up voice (it downloads the speech models).", "Tap Check again."]} />
    </>
  );
}
