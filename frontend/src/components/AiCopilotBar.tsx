import { useMutation, useQuery } from '@tanstack/react-query';
import { Languages, ListChecks, Sparkles, Wand2, X } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { client } from '@/lib/client';

/**
 * Agent Copilot bar (Phase 4 feature 2) — Haiku-tier assists that operate on the
 * composer draft or the whole conversation. Hidden unless the workspace has the AI
 * add-on. Suggest/Polish/Shorten/Translate replace the draft; Summarize shows a
 * dismissible panel. All calls are add-on-gated + metered server-side.
 */
export function AiCopilotBar({
  chatName,
  draft,
  setDraft,
}: {
  chatName: string;
  draft: string;
  setDraft: (value: string) => void;
}): JSX.Element | null {
  const settings = useQuery({ queryKey: ['ai-settings'], queryFn: () => client.aiSettings() });
  const [summary, setSummary] = useState<string | null>(null);

  const suggest = useMutation({
    mutationFn: () => client.copilotSuggestReply(chatName),
    onSuccess: (r) => setDraft(r.text),
  });
  const rewrite = useMutation({
    mutationFn: (mode: 'polish' | 'shorten') => client.copilotRewrite(draft, mode),
    onSuccess: (r) => setDraft(r.text),
  });
  const translate = useMutation({
    mutationFn: () => client.copilotTranslate(draft, 'English'),
    onSuccess: (r) => setDraft(r.text),
  });
  const summarize = useMutation({
    mutationFn: () => client.copilotSummarize(chatName),
    onSuccess: (r) => setSummary(r.text),
  });

  if (!settings.data?.has_ai) {
    return null;
  }

  const busy =
    suggest.isPending || rewrite.isPending || translate.isPending || summarize.isPending;
  const hasDraft = draft.trim().length > 0;
  const isError =
    suggest.isError || rewrite.isError || translate.isError || summarize.isError;

  return (
    <div data-testid="copilot-bar" className="mb-2 flex flex-wrap items-center gap-1.5">
      <span className="flex items-center gap-1 text-xs font-medium text-primary">
        <Sparkles className="h-3.5 w-3.5" /> Copilot
      </span>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 px-2 text-xs"
        disabled={busy}
        onClick={() => suggest.mutate()}
      >
        Suggest reply
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        disabled={busy || !hasDraft}
        onClick={() => rewrite.mutate('polish')}
      >
        <Wand2 className="h-3.5 w-3.5" /> Polish
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 px-2 text-xs"
        disabled={busy || !hasDraft}
        onClick={() => rewrite.mutate('shorten')}
      >
        Shorten
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        disabled={busy || !hasDraft}
        onClick={() => translate.mutate()}
      >
        <Languages className="h-3.5 w-3.5" /> Translate
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-7 gap-1 px-2 text-xs"
        disabled={busy}
        onClick={() => summarize.mutate()}
      >
        <ListChecks className="h-3.5 w-3.5" /> Summarize
      </Button>
      {busy && <span className="text-xs text-muted-foreground">thinking…</span>}
      {summary !== null && (
        <div
          data-testid="copilot-summary"
          className="mt-1 w-full rounded-md border bg-muted/40 p-2 text-xs"
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="font-medium">Summary</span>
            <button type="button" aria-label="Dismiss summary" onClick={() => setSummary(null)}>
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <p className="whitespace-pre-wrap text-muted-foreground">{summary}</p>
        </div>
      )}
      {isError && (
        <p role="alert" className="w-full text-xs text-destructive">
          Copilot unavailable — check your AI add-on and credits.
        </p>
      )}
    </div>
  );
}
