import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
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

const schema = z
  .object({
    password: z.string().min(8, 'At least 8 characters'),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  });

type ResetForm = z.infer<typeof schema>;

/** Landing page for an emailed reset link (/reset-password?token=…). On success
 * the user signs in with the new password — no session is issued here, and every
 * previously-open session was destroyed server-side. */
export default function ResetPasswordPage(): React.JSX.Element {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [failed, setFailed] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResetForm>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    setFailed(null);
    try {
      await client.resetPassword(token, values.password);
      setDone(true);
      setTimeout(() => void navigate('/login'), 1500);
    } catch {
      setFailed('This reset link is invalid or has expired — request a new one.');
    }
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">Choose a new password</CardTitle>
          <CardDescription>
            {done ? 'Password updated' : 'This link works once'}
          </CardDescription>
        </CardHeader>

        {!token ? (
          <CardContent className="grid gap-3">
            <p role="alert" className="text-sm text-destructive">
              This link is missing its token. Request a fresh one.
            </p>
            <Link
              to="/forgot-password"
              className="text-sm text-primary underline-offset-2 hover:underline"
            >
              Send a new reset link
            </Link>
          </CardContent>
        ) : done ? (
          <CardContent>
            <p data-testid="reset-done" className="text-sm text-muted-foreground">
              Your password is updated and every other session was signed out. Taking you
              to sign in…
            </p>
          </CardContent>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} noValidate>
            <CardContent className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="password">New password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  {...register('password')}
                />
                {errors.password && (
                  <p role="alert" className="text-sm text-destructive">
                    {errors.password.message}
                  </p>
                )}
              </div>
              <div className="grid gap-2">
                <Label htmlFor="confirm">Confirm new password</Label>
                <Input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  {...register('confirm')}
                />
                {errors.confirm && (
                  <p role="alert" className="text-sm text-destructive">
                    {errors.confirm.message}
                  </p>
                )}
              </div>
            </CardContent>
            <CardFooter className="flex-col gap-2">
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                Update password
              </Button>
              {failed && (
                <p role="alert" className="text-sm text-destructive">
                  {failed}{' '}
                  <Link
                    to="/forgot-password"
                    className="text-primary underline-offset-2 hover:underline"
                  >
                    Request a new link
                  </Link>
                </p>
              )}
            </CardFooter>
          </form>
        )}
      </Card>
    </main>
  );
}
