import { useState } from "react";
import type { Api } from "@/lib/api";
import { VALUE_CONTRACT } from "@/lib/constants";
import type { Answer, Citation } from "@/lib/contracts";
import { AnswerView } from "./AnswerView";

const SUGGESTIONS = [
  "What was Aurora's FY2024 revenue and how did it grow?",
  "What is the gross margin and the customer concentration?",
  "What is the CEO's compensation package?",
];

type AskState =
  | { status: "idle" }
  | { status: "loading"; question: string }
  | { status: "error"; message: string }
  | { status: "answer"; answer: Answer };

export function AskTab({
  api,
  dealId,
  onOpen,
  activeChunk,
  onBackend,
}: {
  api: Api;
  dealId: string;
  onOpen: (citation: Citation, answer: Answer) => void;
  activeChunk: string | null;
  onBackend: (backend: string) => void;
}) {
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<AskState>({ status: "idle" });

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setState({ status: "loading", question: trimmed });
    try {
      const served = await api.ask(dealId, trimmed);
      onBackend(served.backend);
      setState({ status: "answer", answer: served.value });
    } catch (error) {
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <div className="ask">
      <form
        className="ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <label htmlFor="question">Question about this deal</label>
        <div className="ask-row">
          <input
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about the data room"
            autoComplete="off"
          />
          <button type="submit" className="primary" disabled={state.status === "loading"}>
            Ask
          </button>
        </div>
        <div className="suggestions">
          {SUGGESTIONS.map((text) => (
            <button
              key={text}
              type="button"
              className="link"
              onClick={() => {
                setQuestion(text);
                void submit(text);
              }}
            >
              {text}
            </button>
          ))}
        </div>
      </form>

      {state.status === "loading" && <p className="muted">Reading the sources for: {state.question}</p>}
      {state.status === "error" && (
        <p className="note" role="alert">
          The question could not be answered: {state.message}
        </p>
      )}
      {state.status === "answer" && (
        <AnswerView
          answer={state.answer}
          onOpen={(citation) => onOpen(citation, state.answer)}
          activeChunk={activeChunk}
        />
      )}

      <footer className="value-contract">{VALUE_CONTRACT}</footer>
    </div>
  );
}
