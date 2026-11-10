import { useState } from "react";
import type { Api } from "@/lib/api";
import { VALUE_CONTRACT } from "@/lib/constants";
import type { Answer, Citation } from "@/lib/contracts";
import { AnswerView } from "./AnswerView";
import { Loading } from "./Loading";

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
        className="plate ask-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
      >
        <div className="plate-b">
        <label htmlFor="question" className="lab">
          Question about this deal
        </label>
        <div className="lg-ask mt">
          <input
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about the data room"
            autoComplete="off"
          />
          <button type="submit" className="btn solid" disabled={state.status === "loading"}>
            Ask
          </button>
        </div>
        </div>
        <div className="plate-b tint chips suggestions">
          {SUGGESTIONS.map((text) => (
            <button
              key={text}
              type="button"
              className="opt"
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

      {state.status === "loading" && <Loading inline />}
      {state.status === "error" && (
        <p className="note bad mt" role="alert">
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

      <footer className="value-contract sub">{VALUE_CONTRACT}</footer>
    </div>
  );
}
