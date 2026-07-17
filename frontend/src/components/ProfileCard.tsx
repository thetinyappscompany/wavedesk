import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

/** Settings → Account: the logged-in user's own name, email and password. */
export default function ProfileCard(): React.JSX.Element {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => client.getProfile() });

  const [name, setName] = useState<string | null>(null); // null = untouched
  const saveName = useMutation({
    mutationFn: (firstName: string) => client.updateProfile(firstName),
    onSuccess: () => {
      setName(null);
      void queryClient.invalidateQueries({ queryKey: ['profile'] });
    },
  });

  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwDone, setPwDone] = useState(false);
  const changePw = useMutation({
    mutationFn: () => client.changePassword(currentPw, newPw),
    onSuccess: () => {
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
      setPwDone(true);
    },
  });

  const displayName = name ?? profile.data?.first_name ?? '';
  const pwMismatch = confirmPw.length > 0 && newPw !== confirmPw;

  return (
    <section aria-label="Profile" className="rounded-lg border p-4">
      <h2 className="font-semibold">Profile</h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Your account details. The email is your login and cannot be changed here.
      </p>

      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (displayName.trim()) {
            saveName.mutate(displayName.trim());
          }
        }}
      >
        <label className="flex-1 text-sm">
          Display name
          <Input
            aria-label="Display name"
            className="mt-1"
            value={displayName}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </label>
        <label className="flex-1 text-sm">
          Email
          <Input aria-label="Email" className="mt-1" value={profile.data?.email ?? ''} disabled />
        </label>
        <Button
          type="submit"
          disabled={
            !displayName.trim() ||
            displayName.trim() === profile.data?.first_name ||
            saveName.isPending
          }
        >
          Save
        </Button>
      </form>
      {saveName.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(saveName.error)}
        </p>
      )}

      <h3 className="mt-5 text-sm font-semibold">Change password</h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Changing your password signs out every other device.
      </p>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPwDone(false);
          if (currentPw && newPw.length >= 8 && newPw === confirmPw) {
            changePw.mutate();
          }
        }}
      >
        <Input
          aria-label="Current password"
          type="password"
          placeholder="Current password"
          value={currentPw}
          onChange={(e) => {
            setCurrentPw(e.target.value);
          }}
        />
        <div className="flex gap-2">
          <Input
            aria-label="New password"
            type="password"
            placeholder="New password (min 8 chars)"
            value={newPw}
            onChange={(e) => {
              setNewPw(e.target.value);
            }}
          />
          <Input
            aria-label="Confirm new password"
            type="password"
            placeholder="Confirm new password"
            value={confirmPw}
            onChange={(e) => {
              setConfirmPw(e.target.value);
            }}
          />
        </div>
        {pwMismatch && (
          <p className="text-xs text-destructive">Passwords do not match.</p>
        )}
        <Button
          type="submit"
          variant="outline"
          disabled={
            !currentPw || newPw.length < 8 || newPw !== confirmPw || changePw.isPending
          }
        >
          Update password
        </Button>
      </form>
      {changePw.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {errorText(changePw.error)}
        </p>
      )}
      {pwDone && (
        <p role="status" className="mt-2 text-xs text-green-600">
          Password updated. Other devices have been signed out.
        </p>
      )}
    </section>
  );
}
