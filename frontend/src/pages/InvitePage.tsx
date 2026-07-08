import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { client } from '@/lib/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

/** Public accept-invite page — the token in the URL is the credential.
 * New teammates set a password; existing users leave it blank. */
export default function InvitePage(): React.JSX.Element {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');

  const accept = useMutation({
    mutationFn: () =>
      client.acceptInvite(token ?? '', {
        ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
        ...(password ? { password } : {}),
      }),
    onSuccess: () => {
      // accept_invite logs the invitee in server-side (session cookie set)
      void navigate('/inbox');
    },
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">Join your team on WaveDesk</CardTitle>
          <CardDescription>
            Set up your account to start answering WhatsApp together.
          </CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            accept.mutate();
          }}
          noValidate
        >
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="full-name">Your name</Label>
              <Input
                id="full-name"
                placeholder="Riya Sharma"
                value={fullName}
                onChange={(e) => {
                  setFullName(e.target.value);
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="password">Choose a password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
              />
              <p className="text-xs text-muted-foreground">
                At least 8 characters. Already have a WaveDesk account? Leave this blank.
              </p>
            </div>
          </CardContent>
          <CardFooter className="flex-col gap-2">
            <Button type="submit" className="w-full" disabled={accept.isPending}>
              Accept invite
            </Button>
            {accept.isError && (
              <p role="alert" className="text-sm text-destructive">
                {accept.error.message.includes('invalid')
                  ? 'This invite link is invalid or was already used.'
                  : accept.error.message}
              </p>
            )}
          </CardFooter>
        </form>
      </Card>
    </main>
  );
}
