import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, Plus, Send, Trash2 } from 'lucide-react';
import type { WdMessageTemplate, WdTemplateCategory, WdTemplateStatus } from '@wavedesk/api-client';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const CATEGORIES: WdTemplateCategory[] = ['utility', 'marketing', 'authentication'];
const STATUS_TONE: Record<WdTemplateStatus, string> = {
  draft: 'bg-muted text-muted-foreground',
  pending: 'bg-amber-500/15 text-amber-600',
  approved: 'bg-emerald-500/15 text-emerald-600',
  rejected: 'bg-destructive/15 text-destructive',
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

function Builder({ onDone }: { onDone: () => void }): React.JSX.Element {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [category, setCategory] = useState<WdTemplateCategory>('utility');
  const [language, setLanguage] = useState('en');
  const [header, setHeader] = useState('');
  const [body, setBody] = useState('');
  const [footer, setFooter] = useState('');

  const create = useMutation({
    mutationFn: () =>
      client.createTemplate({
        templateName: name.trim(),
        bodyText: body,
        category,
        language: language.trim() || 'en',
        ...(header.trim() ? { headerText: header.trim() } : {}),
        ...(footer.trim() ? { footerText: footer.trim() } : {}),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['templates'] });
      onDone();
    },
  });

  return (
    <form
      className="space-y-3 rounded-lg border p-4"
      data-testid="template-builder"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim() && body.trim()) {
          create.mutate();
        }
      }}
    >
      <div className="flex flex-wrap gap-2">
        <Input
          aria-label="Template name"
          placeholder="order_update"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <select
          aria-label="Category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value as WdTemplateCategory);
          }}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <Input
          aria-label="Language"
          className="w-24"
          value={language}
          onChange={(e) => {
            setLanguage(e.target.value);
          }}
        />
      </div>
      <Input
        aria-label="Header text"
        placeholder="Header (optional)"
        value={header}
        onChange={(e) => {
          setHeader(e.target.value);
        }}
      />
      <textarea
        aria-label="Body text"
        placeholder="Hi {{1}}, your order {{2}} has shipped."
        value={body}
        rows={3}
        onChange={(e) => {
          setBody(e.target.value);
        }}
        className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
      />
      <p className="text-xs text-muted-foreground">
        Use positional variables {'{{1}}'}, {'{{2}}'} … filled at send time.
      </p>
      <Input
        aria-label="Footer text"
        placeholder="Footer (optional)"
        value={footer}
        onChange={(e) => {
          setFooter(e.target.value);
        }}
      />
      <div className="flex gap-2">
        <Button type="submit" disabled={!name.trim() || !body.trim() || create.isPending}>
          Save template
        </Button>
        <Button type="button" variant="outline" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {create.isError && (
        <p role="alert" className="text-xs text-destructive">
          {errorText(create.error)}
        </p>
      )}
    </form>
  );
}

export default function TemplatesPage(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [building, setBuilding] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const templates = useQuery({ queryKey: ['templates'], queryFn: () => client.listTemplates() });
  const onSuccess = (): void => {
    void queryClient.invalidateQueries({ queryKey: ['templates'] });
  };
  const submit = useMutation({
    mutationFn: (name: string) => client.submitTemplate(name),
    onSuccess: (result) => {
      setNote(result.note ?? null);
      onSuccess();
    },
  });
  const remove = useMutation({ mutationFn: (name: string) => client.deleteTemplate(name), onSuccess });

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <FileText className="h-5 w-5" />
        <h1 className="text-lg font-semibold">Message templates</h1>
        {!building && (
          <Button size="sm" onClick={() => setBuilding(true)}>
            <Plus className="mr-1 h-3.5 w-3.5" />
            New template
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Pre-approved templates for Cloud API sends. Submitting for Meta approval needs a connected
        Cloud API number.
      </p>

      {note && (
        <p role="status" className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          {note}
        </p>
      )}

      {building && (
        <Builder
          onDone={() => {
            setBuilding(false);
          }}
        />
      )}

      <ul className="space-y-2">
        {(templates.data ?? []).map((tpl: WdMessageTemplate) => (
          <li
            key={tpl.name}
            data-testid="template-row"
            className="flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-mono text-sm font-medium">{tpl.template_name}</span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">
                  {tpl.category}
                </span>
                <span className="rounded border px-1 text-[10px] text-muted-foreground">
                  {tpl.language}
                </span>
                <span className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS_TONE[tpl.status]}`}>
                  {tpl.status}
                </span>
              </div>
              <div className="truncate text-xs text-muted-foreground">{tpl.body_text}</div>
            </div>
            {(tpl.status === 'draft' || tpl.status === 'rejected') && (
              <button
                type="button"
                aria-label={`Submit ${tpl.template_name}`}
                className="rounded p-1 text-primary hover:bg-accent"
                onClick={() => {
                  submit.mutate(tpl.name);
                }}
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              aria-label={`Delete ${tpl.template_name}`}
              className="rounded p-1 text-destructive hover:bg-accent"
              onClick={() => {
                remove.mutate(tpl.name);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
        {templates.data?.length === 0 && !building && (
          <li className="rounded-lg border px-3 py-6 text-center text-sm text-muted-foreground">
            No templates yet — create one for Cloud API sends.
          </li>
        )}
      </ul>
    </div>
  );
}
