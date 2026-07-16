import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import type { WdAiAgentConfig, WdTeam } from '@wavedesk/api-client';

import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/**
 * AI Auto-Agent config (P4.3): enable + persona + confidence threshold + handoff
 * team + after-hours mode, a knowledge base (add/list/delete → embed), and a live
 * answer preview. Locked without the AI add-on; mutations gated by canManage.
 */
export default function AiAgentCard({ canManage }: { canManage: boolean }): React.JSX.Element {
  const queryClient = useQueryClient();
  const ai = useQuery({ queryKey: ['ai-settings'], queryFn: () => client.aiSettings() });
  const enabledAi = ai.data?.has_ai === true;
  const config = useQuery({
    queryKey: ['agent-config'],
    queryFn: () => client.getAgentConfig(),
    enabled: enabledAi,
  });
  const knowledge = useQuery({
    queryKey: ['knowledge'],
    queryFn: () => client.listKnowledge(),
    enabled: enabledAi,
  });
  const teams = useQuery({ queryKey: ['teams'], queryFn: () => client.listTeams() });

  const [form, setForm] = useState<Partial<WdAiAgentConfig>>({});
  useEffect(() => {
    if (config.data) setForm(config.data);
  }, [config.data]);

  const save = useMutation({
    mutationFn: () =>
      client.updateAgentConfig({
        enabled: Boolean(form.enabled),
        persona_prompt: form.persona_prompt ?? '',
        confidence_threshold: form.confidence_threshold ?? 0.6,
        handoff_team: form.handoff_team ?? undefined,
        after_hours_only: Boolean(form.after_hours_only),
        auto_ticket: Boolean(form.auto_ticket),
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['agent-config'] }),
  });

  const [kTitle, setKTitle] = useState('');
  const [kContent, setKContent] = useState('');
  const addKnowledge = useMutation({
    mutationFn: () => client.createKnowledge(kTitle, kContent),
    onSuccess: () => {
      setKTitle('');
      setKContent('');
      void queryClient.invalidateQueries({ queryKey: ['knowledge'] });
    },
  });
  const delKnowledge = useMutation({
    mutationFn: (doc: string) => client.deleteKnowledge(doc),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['knowledge'] }),
  });

  const [question, setQuestion] = useState('');
  const preview = useMutation({ mutationFn: () => client.previewAnswer(question) });

  if (ai.data && !enabledAi) {
    return (
      <section className="rounded-lg border p-4" data-testid="ai-agent-card">
        <h3 className="font-semibold">AI Auto-Agent</h3>
        <p className="mt-1 text-sm text-muted-foreground">Locked — requires the AI add-on.</p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border p-4" data-testid="ai-agent-card">
      <h3 className="font-semibold">AI Auto-Agent</h3>
      <p className="mb-3 text-sm text-muted-foreground">
        Answer customer DMs from your knowledge base; hand off to a human when unsure.
      </p>

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={Boolean(form.enabled)}
            disabled={!canManage}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          />
          Enabled
        </label>
        <label className="block text-sm">
          Persona / instructions
          <textarea
            aria-label="Persona"
            rows={2}
            className="mt-1 w-full rounded-md border px-2 py-1 text-sm"
            value={form.persona_prompt ?? ''}
            disabled={!canManage}
            onChange={(e) => setForm((f) => ({ ...f, persona_prompt: e.target.value }))}
          />
        </label>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Confidence threshold
            <Input
              type="number"
              step="0.05"
              min="0"
              max="1"
              aria-label="Confidence threshold"
              className="mt-1 w-24"
              value={form.confidence_threshold ?? 0.6}
              disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, confidence_threshold: Number(e.target.value) }))}
            />
          </label>
          <label className="text-sm">
            Handoff team
            <select
              aria-label="Handoff team"
              className="mt-1 block h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              value={form.handoff_team ?? ''}
              disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, handoff_team: e.target.value }))}
            >
              <option value="">— none —</option>
              {teams.data?.map((t: WdTeam) => (
                <option key={t.name} value={t.name}>
                  {t.team_name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(form.after_hours_only)}
              disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, after_hours_only: e.target.checked }))}
            />
            After-hours only
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={Boolean(form.auto_ticket)}
              disabled={!canManage}
              onChange={(e) => setForm((f) => ({ ...f, auto_ticket: e.target.checked }))}
            />
            Auto-create tickets
          </label>
        </div>
        {canManage && (
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </Button>
        )}
      </div>

      <div className="mt-4 border-t pt-3">
        <h4 className="mb-2 text-sm font-medium">Knowledge base</h4>
        <ul className="mb-2 space-y-1" data-testid="knowledge-list">
          {(knowledge.data ?? []).map((k) => (
            <li key={k.name} className="flex items-center justify-between text-sm">
              <span className="truncate">
                {k.title}{' '}
                <span className="text-xs text-muted-foreground">({k.embedding_status})</span>
              </span>
              {canManage && (
                <button
                  type="button"
                  aria-label={`Delete ${k.title}`}
                  onClick={() => delKnowledge.mutate(k.name)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </button>
              )}
            </li>
          ))}
          {knowledge.data?.length === 0 && (
            <li className="text-xs text-muted-foreground">No knowledge yet.</li>
          )}
        </ul>
        {canManage && (
          <div className="space-y-1">
            <Input
              aria-label="Knowledge title"
              placeholder="Title"
              value={kTitle}
              onChange={(e) => setKTitle(e.target.value)}
            />
            <textarea
              aria-label="Knowledge content"
              placeholder="Paste an FAQ or policy…"
              rows={2}
              className="w-full rounded-md border px-2 py-1 text-sm"
              value={kContent}
              onChange={(e) => setKContent(e.target.value)}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!kTitle.trim() || !kContent.trim() || addKnowledge.isPending}
              onClick={() => addKnowledge.mutate()}
            >
              Add document
            </Button>
          </div>
        )}
      </div>

      <div className="mt-4 border-t pt-3">
        <h4 className="mb-2 text-sm font-medium">Test the agent</h4>
        <div className="flex gap-2">
          <Input
            aria-label="Test question"
            placeholder="Ask a customer question…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={!question.trim() || preview.isPending}
            onClick={() => preview.mutate()}
          >
            Preview
          </Button>
        </div>
        {preview.data && (
          <p className="mt-2 rounded-md border bg-muted/40 p-2 text-sm" data-testid="preview-result">
            {preview.data.action === 'reply'
              ? preview.data.text
              : `↪ Handoff (${preview.data.reason ?? 'low confidence'})`}
          </p>
        )}
        {(save.isError || addKnowledge.isError || preview.isError) && (
          <p role="alert" className="mt-1 text-xs text-destructive">
            {errorText(save.error ?? addKnowledge.error ?? preview.error)}
          </p>
        )}
      </div>
    </section>
  );
}
