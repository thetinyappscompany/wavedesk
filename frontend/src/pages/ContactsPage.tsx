import { useEffect, useRef, useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const PAGE_SIZE = 50;

function ImportPanel(): React.JSX.Element {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [importName, setImportName] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const status = useQuery({
    queryKey: ['contact-import', importName],
    queryFn: () => client.importStatus(importName ?? ''),
    enabled: !!importName,
    refetchInterval: (query) => {
      const state = query.state.data?.status;
      return state === 'pending' || state === 'processing' ? 1500 : false;
    },
  });

  const finished = status.data?.status === 'completed' || status.data?.status === 'failed';
  useEffect(() => {
    if (status.data?.status === 'completed') {
      void queryClient.invalidateQueries({ queryKey: ['contacts'] });
    }
  }, [status.data?.status, queryClient]);

  const startImport = async (file: File): Promise<void> => {
    setUploadError(null);
    try {
      const text = await file.text();
      const result = await client.importContacts(text, file.name);
      setImportName(result.import);
    } catch {
      setUploadError('Import failed to start — are you an owner/admin?');
    }
  };

  const downloadErrors = (): void => {
    if (!status.data?.error_csv) {
      return;
    }
    const blob = new Blob([status.data.error_csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'rejected-contacts.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-2">
      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        data-testid="import-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            void startImport(file);
          }
          e.target.value = '';
        }}
      />
      <Button
        variant="outline"
        onClick={() => {
          fileInput.current?.click();
        }}
      >
        <Upload className="mr-1 h-4 w-4" /> Import CSV
      </Button>
      <p className="text-xs text-muted-foreground">
        Columns: name, phone, email — anything else becomes a custom attribute. Rows merge
        into existing contacts by phone.
      </p>
      {uploadError && (
        <p role="alert" className="text-xs text-destructive">
          {uploadError}
        </p>
      )}
      {status.data && (
        <div data-testid="import-status" className="rounded-md border p-2 text-xs">
          {!finished && <p>Importing… {status.data.status}</p>}
          {status.data.status === 'completed' && (
            <p>
              Done: {status.data.imported_rows} new · {status.data.merged_rows} updated ·{' '}
              {status.data.rejected_rows} rejected
            </p>
          )}
          {status.data.status === 'failed' && (
            <p role="alert" className="text-destructive">
              Import failed: {status.data.failure_reason ?? 'unknown error'}
            </p>
          )}
          {status.data.error_csv && (
            <button
              type="button"
              className="mt-1 text-primary underline"
              onClick={downloadErrors}
            >
              Download rejected rows
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function ContactsPage(): React.JSX.Element {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [search]);

  const contacts = useQuery({
    queryKey: ['contacts', debouncedSearch],
    queryFn: () =>
      client.listContacts({ search: debouncedSearch || undefined, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const rows = contacts.data?.contacts ?? [];

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">Contacts</h1>
          <p className="text-sm text-muted-foreground">
            {contacts.data ? `${String(contacts.data.total)} contacts` : 'Loading…'}
          </p>
        </div>
        <ImportPanel />
      </div>

      <Input
        placeholder="Search name, phone or email…"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
        }}
      />

      {contacts.isError && (
        <p role="alert" className="text-sm text-destructive">
          Failed to load contacts.
        </p>
      )}

      <div className="overflow-hidden rounded-md border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Phone</th>
              <th className="px-3 py-2">Email</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((contact) => (
              <tr key={contact.name} data-testid="contact-row" className="border-t">
                <td className="px-3 py-2">{contact.full_name ?? '—'}</td>
                <td className="px-3 py-2 text-muted-foreground">+{contact.phone}</td>
                <td className="px-3 py-2 text-muted-foreground">{contact.email ?? '—'}</td>
              </tr>
            ))}
            {rows.length === 0 && !contacts.isLoading && (
              <tr>
                <td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                  No contacts yet — they appear automatically from incoming chats, or import
                  a CSV.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
