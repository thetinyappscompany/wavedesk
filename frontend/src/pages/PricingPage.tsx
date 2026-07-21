import { Check, Sparkles } from 'lucide-react';
import { Link } from 'react-router';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** Public plan matrix (launch defaults, master doc §3.2). Client-facing prices
 * only — the AI add-on is presented as a flat monthly price, never token math. */
const PLANS = [
  {
    key: 'trial',
    name: 'Free Trial',
    price: 'Free',
    period: '14 days',
    numbers: '1 WhatsApp number',
    agents: '3 agents',
    retention: '30-day history',
    highlight: false,
    cta: 'Start free trial',
  },
  {
    key: 'starter',
    name: 'Starter',
    price: '₹1,499',
    period: 'per month',
    numbers: '2 WhatsApp numbers',
    agents: '5 agents',
    retention: '12-month history',
    highlight: false,
    cta: 'Start with Starter',
  },
  {
    key: 'pro',
    name: 'Pro',
    price: '₹3,999',
    period: 'per month',
    numbers: '5 WhatsApp numbers',
    agents: '15 agents',
    retention: '24-month history',
    highlight: true,
    cta: 'Start with Pro',
  },
  {
    key: 'business',
    name: 'Business',
    price: '₹4,999',
    period: 'per month',
    numbers: '10 WhatsApp numbers',
    agents: '30 agents',
    retention: 'Custom retention',
    highlight: false,
    cta: 'Start with Business',
  },
] as const;

const EVERY_PLAN = [
  'Shared team inbox for WhatsApp',
  'Group management & monitoring',
  'Broadcasts with anti-ban protection',
  'Automation rules, SLAs & routing',
  'Contacts, segments & analytics',
  'Tickets, labels, macros & private notes',
];

export default function PricingPage(): React.JSX.Element {
  return (
    <main className="min-h-screen bg-muted/40">
      <div className="mx-auto max-w-5xl px-4 py-12">
        <header className="text-center">
          <Link to="/login" className="text-sm font-semibold text-primary">
            WaveDesk
          </Link>
          <h1 className="mt-2 text-3xl font-bold">Simple pricing, per workspace</h1>
          <p className="mt-2 text-muted-foreground">
            Every plan starts with a 14-day free trial — no card required. Annual billing gets
            2 months free.
          </p>
        </header>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PLANS.map((plan) => (
            <div
              key={plan.key}
              data-testid="pricing-tier"
              className={cn(
                'flex flex-col rounded-xl border bg-background p-5 shadow-sm',
                plan.highlight && 'border-primary ring-1 ring-primary',
              )}
            >
              {plan.highlight && (
                <span className="mb-2 self-start rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                  Most popular
                </span>
              )}
              <h2 className="text-lg font-semibold">{plan.name}</h2>
              <p className="mt-1">
                <span className="text-2xl font-bold">{plan.price}</span>{' '}
                <span className="text-sm text-muted-foreground">{plan.period}</span>
              </p>
              <ul className="mt-4 flex-1 space-y-2 text-sm">
                {[plan.numbers, plan.agents, plan.retention].map((line) => (
                  <li key={line} className="flex items-start gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                    {line}
                  </li>
                ))}
              </ul>
              <Link
                to="/signup"
                className={cn(
                  buttonVariants({ variant: plan.highlight ? 'default' : 'outline' }),
                  'mt-5 w-full',
                )}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>

        <section className="mt-10 grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border bg-background p-5">
            <h3 className="font-semibold">Included in every plan</h3>
            <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              {EVERY_PLAN.map((feature) => (
                <li key={feature} className="flex items-start gap-2">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  {feature}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border bg-background p-5">
            <h3 className="inline-flex items-center gap-1.5 font-semibold">
              <Sparkles className="h-4 w-4 text-primary" /> AI Add-on — ₹1,200/mo
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Adds the full AI layer to any plan: auto-agent with your knowledge base, agent
              copilot, message flagging, voice-note transcription and summaries. Includes
              monthly AI usage; buy AI credits from your wallet if you need more, or bring
              your own API key.
            </p>
            <p className="mt-3 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Add-ons:</span> extra WhatsApp
              number ₹499/mo · extra agent seat ₹299/mo.
            </p>
          </div>
        </section>

        <footer className="mt-10 text-center text-sm text-muted-foreground">
          Prices exclude GST. Questions?{' '}
          <Link to="/signup" className="text-primary underline-offset-2 hover:underline">
            Start your free trial
          </Link>{' '}
          or{' '}
          <Link to="/login" className="text-primary underline-offset-2 hover:underline">
            sign in
          </Link>
          .
        </footer>
      </div>
    </main>
  );
}
