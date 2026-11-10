import { useEffect, useRef, useState } from "react";
import type { Api } from "@/lib/api";
import { VALUE_CONTRACT } from "@/lib/constants";
import type { Answer, Citation } from "@/lib/contracts";
import { AnswerCard } from "./AnswerCard";
import { Loading } from "./Loading";

const SUGGESTIONS = [
  "What was Aurora's FY2024 revenue and how did it grow?",
  "What is the gross margin and the customer concentration?",
  "What is the CEO's compensation package?",
];

type Turn =
  | { id: number; question: string; status: "loading" }
  | { id: number; question: string; status: "error"; message: string }
  | { id: number; question: string; status: "answer"; answer: Answer };

export function AskPage({
  api,
  dealId,
  onOpen,
  activeChunk,
}: {
  api: Api;
  dealId: string;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const counter = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.status === "loading");

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [turns.length]);

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    const id = ++counter.current;
    setQuestion("");
    setTurns((t) => [...t, { id, question: trimmed, status: "loading" }]);
    try {
      const served = await api.ask(dealId, trimmed);
      setTurns((t) => t.map((x) => (x.id === id ? { id, question: trimmed, status: "answer", answer: served.value } : x)));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTurns((t) => t.map((x) => (x.id === id ? { id, question: trimmed, status: "error", message } : x)));
    }
  }

  return (
    <div className="chat">
      {turns.length === 0 && (
        <div className="chat-empty">
          <p className="sub">Ask anything about the data room. Every answer shows its sources and how sure it is.</p>
          <div className="chips mt">
            {SUGGESTIONS.map((text) => (
              <button key={text} type="button" className="opt" onClick={() => void submit(text)}>
                {text}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="thread">
        {turns.map((turn) => (
          <div key={turn.id} className="turn">
            <p className="bubble">{turn.question}</p>
            {turn.status === "loading" && <Loading inline />}
            {turn.status === "error" && (
              <p className="note bad" role="alert">
                The question could not be answered: {turn.message}
              </p>
            )}
            {turn.status === "answer" && <AnswerCard answer={turn.answer} onOpen={onOpen} activeChunk={activeChunk} />}
          </div>
        ))}
        <div ref={end} />
      </div>

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <label htmlFor="question" className="sr">
          Question about this deal
        </label>
        <input
          id="question"
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about the data room, e.g. FY2024 EBITDA margin"
          autoComplete="off"
        />
        <button type="submit" className="btn solid" disabled={busy}>
          Send
        </button>
      </form>
      <footer className="value-contract sub">{VALUE_CONTRACT}</footer>
    </div>
  );
}
