import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link } from 'react-router';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { client } from '@/lib/client';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

const schema = z.object({ email: z.string().email('Enter a valid email') });
type ForgotForm = z.infer<typeof schema>;

/** Public "forgot password". The confirmation is deliberately the same whether
 * or not the address has an account — the UI must never reveal which. */
export default function ForgotPasswordPage(): React.JSX.Element {
  const [sent, setSent] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ForgotForm>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    // A failure here would also leak signal, so the outcome is always "sent".
    await client.requestPasswordReset(values.email).catch(() => undefined);
    setSent(true);
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1 text-center">
          <CardTitle className="text-2xl">Reset your password</CardTitle>
          <CardDescription>
            {sent
              ? 'Check your inbox'
              : "We'll email you a link to choose a new password"}
          </CardDescription>
        </CardHeader>
        {sent ? (
          <CardContent className="grid gap-3">
            <p data-testid="reset-sent" className="text-sm text-muted-foreground">
              If that email has a WaveDesk account, a reset link is on its way. The link
              works once and expires in 60 minutes.
            </p>
            <Link to="/login" className={cn(buttonVariants({ variant: 'outline' }), 'w-full')}>
              Back to sign in
            </Link>
          </CardContent>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} noValidate>
            <CardContent className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@company.com"
                  autoComplete="email"
                  {...register('email')}
                />
                {errors.email && (
                  <p role="alert" className="text-sm text-destructive">
                    {errors.email.message}
                  </p>
                )}
              </div>
            </CardContent>
            <CardFooter className="flex-col gap-2">
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                Send reset link
              </Button>
              <p className="text-sm text-muted-foreground">
                Remembered it?{' '}
                <Link to="/login" className="text-primary underline-offset-2 hover:underline">
                  Sign in
                </Link>
              </p>
            </CardFooter>
          </form>
        )}
      </Card>
    </main>
  );
}
