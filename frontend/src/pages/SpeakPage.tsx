import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { api, ApiError, errorMessage, type ServiceStatus } from "../api/client";
import { AppBar, Page } from "../components/AppBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { Button, Card, ErrorBox, Spinner, buttonClass, cx } from "../components/ui";
import {
  LiveTranscriber,
  MAX_SECONDS,
  RecorderError,
  VoiceRecorder,
  secureAddress,
  voiceSupportProblem,
} from "../voice/recorder";

type Phase =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "recording" }
  | { kind: "transcribing" }
  | { kind: "saving" }
  | { kind: "error"; message: string; canRetryFinal?: boolean; insecure?: boolean };

const HINT = "Say their name, where you met, what they do, and anything to follow up on.";
const LANG_NOTE = "Works in English and major European languages.";

function mmss(sec: number) {
  const s = Math.floor(sec);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** Splits text into the part that matched the previous result (stable) and the new tail. */
function splitStable(prev: string, next: string): [string, string] {
  const a = prev.split(/\s+/).filter(Boolean);
  const b = next.split(/\s+/).filter(Boolean);
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i++;
  return [b.slice(0, i).join(" "), b.slice(i).join(" ")];
}

export default function SpeakPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [asr, setAsr] = useState<ServiceStatus | null | "unknown">(null); // null = checking
  const [seconds, setSeconds] = useState(0);
  const [text, setText] = useState("");
  const [stable, setStable] = useState("");
  const [liveIssue, setLiveIssue] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const recRef = useRef<VoiceRecorder | null>(null);
  const liveRef = useRef<LiveTranscriber | null>(null);
  const textRef = useRef("");
  const finishing = useRef(false);
  const support = voiceSupportProblem();

  // Voice availability from /api/health.
  useEffect(() => {
    const ctrl = new AbortController();
    api
      .health({ signal: ctrl.signal, timeoutMs: 8000 })
      .then((h) => setAsr(h.asr ?? "unknown"))
      .catch(() => {
        if (!ctrl.signal.aborted) setAsr("unknown");
      });
    return () => ctrl.abort();
  }, []);

  // Timer while recording.
  useEffect(() => {
    if (phase.kind !== "recording") return;
    const t = setInterval(() => setSeconds(recRef.current?.seconds ?? 0), 250);
    return () => clearInterval(t);
  }, [phase.kind]);

  // Never leave the mic on when the page goes away.
  useEffect(
    () => () => {
      liveRef.current?.stop();
      void recRef.current?.discard();
    },
    [],
  );

  const applyText = useCallback((t: string) => {
    const [s] = splitStable(textRef.current, t);
    textRef.current = t;
    setStable(s);
    setText(t);
  }, []);

  const finish = useCallback(
    async (opts: { useLiveText?: boolean } = {}) => {
      const rec = recRef.current;
      if (!rec || finishing.current) return;
      finishing.current = true;
      liveRef.current?.stop();
      liveRef.current = null;
      await rec.stop();
      setSeconds(rec.seconds);

      let finalText = textRef.current;
      if (!opts.useLiveText) {
        setPhase({ kind: "transcribing" });
        try {
          const r = await api.transcribe(rec.wav());
          finalText = r.text;
          applyText(finalText);
          setStable(finalText);
        } catch (e) {
          finishing.current = false;
          const hasLive = textRef.current.trim().length > 0;
          setPhase({
            kind: "error",
            message: `${errorMessage(e)}${hasLive ? " You can save what was heard so far, or try again." : ""}`,
            canRetryFinal: true,
          });
          return;
        }
      }

      if (!finalText.trim()) {
        finishing.current = false;
        await rec.discard();
        recRef.current = null;
        setPhase({ kind: "error", message: "Nothing was heard. Try again a little closer to the microphone." });
        return;
      }

      setPhase({ kind: "saving" });
      try {
        const c = await api.createContact({ source: "voice", raw_notes: finalText.trim(), enrich: true });
        await rec.discard();
        recRef.current = null;
        navigate(`/c/${c.id}`, { replace: true, state: { justCreated: true } });
      } catch (e) {
        finishing.current = false;
        setPhase({
          kind: "error",
          message: `Not saved. ${errorMessage(e)} What was heard is still here.`,
          canRetryFinal: true,
        });
      }
    },
    [applyText, navigate],
  );

  const start = async () => {
    if (phase.kind === "starting" || phase.kind === "recording") return;
    setLiveIssue(null);
    setText("");
    setStable("");
    textRef.current = "";
    setSeconds(0);
    finishing.current = false;
    setPhase({ kind: "starting" });
    const rec = new VoiceRecorder({
      onAutoStop: () => {
        toast(`Recording stopped at the ${MAX_SECONDS / 60}-minute limit.`);
        void finish();
      },
      onTrackEnded: () => {
        toast("The microphone stopped. Saving what was recorded.", "error");
        void finish();
      },
    });
    try {
      await rec.start();
    } catch (e) {
      setPhase({
        kind: "error",
        message: e instanceof RecorderError ? e.message : "Couldn't start the microphone. Try again.",
        insecure: e instanceof RecorderError && e.kind === "insecure",
      });
      return;
    }
    recRef.current = rec;
    const live = new LiveTranscriber(
      rec,
      (wav, signal) => api.transcribe(wav, { signal }),
      (t) => {
        setLiveIssue(null);
        applyText(t);
      },
      (e) => {
        if (e instanceof ApiError && e.code === "asr_unavailable") setLiveIssue(e.message);
        else setLiveIssue("Live text paused — still recording. It will catch up when you stop.");
      },
    );
    liveRef.current = live;
    live.start();
    setPhase({ kind: "recording" });
  };

  const cancel = () => {
    if ((recRef.current?.seconds ?? 0) > 5) setConfirmCancel(true);
    else void discardAndLeave();
  };

  const discardAndLeave = async () => {
    liveRef.current?.stop();
    await recRef.current?.discard();
    recRef.current = null;
    navigate("/", { replace: true });
  };

  const asrUnavailable = asr && asr !== "unknown" && !asr.available ? asr : null;
  const blocked = !!support || !!asrUnavailable;
  const recording = phase.kind === "recording";
  const busy = phase.kind === "starting" || phase.kind === "transcribing" || phase.kind === "saving";
  const tail = text.slice(stable.length).trim();
  const showTranscript = text || recording || busy || (phase.kind === "error" && phase.canRetryFinal);

  return (
    <>
      <AppBar title="New contact" back />
      <Page>
        <h1 className="sr-only">Speak a new contact</h1>
        <p className="text-body text-navy-500">{HINT}</p>

        {support && (
          <div className="mt-6">
            <ErrorBox
              title="Voice can't start on this page"
              action={
                <div className="flex flex-wrap gap-3">
                  {support.kind === "insecure" && (
                    <a href={secureAddress() + "/speak"} className={buttonClass("primary")}>
                      Open secure address
                    </a>
                  )}
                  <Link to="/new" className={buttonClass("secondary")}>
                    Type instead
                  </Link>
                </div>
              }
            >
              {support.message}
            </ErrorBox>
          </div>
        )}

        {!support && asrUnavailable && (
          <div className="mt-6">
            <ErrorBox
              title="Voice isn't ready"
              action={
                <div className="flex flex-wrap gap-3">
                  <Link to="/settings" className={buttonClass("secondary")}>
                    Open Settings
                  </Link>
                  <Link to="/new" className={buttonClass("secondary")}>
                    Type instead
                  </Link>
                </div>
              }
            >
              {asrUnavailable.detail ?? "Voice is still setting up on your laptop. Try again in a minute."}
            </ErrorBox>
          </div>
        )}

        {showTranscript && (
          <Card as="div" className="mt-6">
            <h2 className="label-caps text-navy-500">Transcript</h2>
            <p className="mt-2 min-h-[72px] whitespace-pre-wrap break-words text-body" aria-live="polite">
              {text ? (
                <>
                  <span>{stable}</span>
                  {tail && (
                    <span className="text-navy-500">
                      {stable ? " " : ""}
                      {tail}
                    </span>
                  )}
                </>
              ) : (
                <span className="text-navy-500">{recording ? "Listening…" : ""}</span>
              )}
            </p>
            {liveIssue && recording && <p className="mt-2 text-meta text-navy-500">{liveIssue}</p>}
          </Card>
        )}

        {phase.kind === "error" && (
          <div className="mt-4">
            <ErrorBox
              action={
                <div className="flex flex-wrap gap-3">
                  {phase.canRetryFinal ? (
                    <>
                      <Button variant="secondary" onClick={() => void finish()}>
                        Try again
                      </Button>
                      {text.trim() && (
                        <Button onClick={() => void finish({ useLiveText: true })}>Save what was heard</Button>
                      )}
                    </>
                  ) : (
                    !phase.insecure && (
                      <Button variant="secondary" onClick={() => void start()}>
                        Try again
                      </Button>
                    )
                  )}
                  <Link to="/new" className={buttonClass("secondary")}>
                    Type instead
                  </Link>
                </div>
              }
            >
              {phase.message}
            </ErrorBox>
          </div>
        )}
        {/* Room for the fixed controls below */}
        <div aria-hidden="true" className="h-40" />
      </Page>

      {/* Thumb zone */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white/95 pb-[calc(12px+env(safe-area-inset-bottom))] pt-4 backdrop-blur">
        <div className="mx-auto flex max-w-[640px] flex-col items-center px-5 md:px-8">
          <p className="text-[20px] font-semibold tabular-nums" aria-live="off">
            <span className="sr-only">Recording time </span>
            {mmss(seconds)}
          </p>
          <div className="relative mt-3 flex size-24 items-center justify-center">
            {recording && (
              <span
                aria-hidden="true"
                className="absolute inset-[-8px] rounded-full border-2 border-navy-100 animate-pulse motion-reduce:animate-none"
              />
            )}
            <button
              type="button"
              onClick={() => (recording ? void finish() : void start())}
              disabled={blocked || busy}
              aria-label={recording ? "Stop and save" : "Start recording"}
              className={cx(
                "relative flex size-24 items-center justify-center rounded-full bg-navy-900 text-white hover:bg-navy-700 disabled:cursor-not-allowed disabled:opacity-50",
                recording && "ring-2 ring-navy-100 ring-offset-2",
              )}
            >
              {busy ? (
                <Spinner className="size-8" />
              ) : recording ? (
                <span className="size-8 rounded-[6px] bg-white" aria-hidden="true" />
              ) : (
                <svg viewBox="0 0 24 24" className="size-10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-2 min-h-6 text-label font-medium text-navy-700" role="status">
            {phase.kind === "starting"
              ? "Starting the microphone…"
              : phase.kind === "recording"
                ? "Recording — tap to stop and save"
                : phase.kind === "transcribing"
                  ? "Transcribing…"
                  : phase.kind === "saving"
                    ? "Saving…"
                    : blocked
                      ? ""
                      : "Tap to start"}
          </p>
          <button
            type="button"
            onClick={cancel}
            disabled={phase.kind === "saving"}
            className="inline-flex min-h-11 items-center rounded-md px-3 text-label font-medium text-navy-700 underline underline-offset-4 disabled:opacity-60"
          >
            Cancel
          </button>
          <p className="text-meta text-navy-500">{LANG_NOTE}</p>
        </div>
      </div>

      <ConfirmDialog
        open={confirmCancel}
        title="Discard this recording?"
        confirmLabel="Discard"
        danger
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => {
          setConfirmCancel(false);
          void discardAndLeave();
        }}
      >
        Nothing will be saved.
      </ConfirmDialog>
    </>
  );
}
