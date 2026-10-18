import { AlertTriangle, ShieldCheck, ShieldX } from 'lucide-react';
import { ProviderOutcome } from '../types/analysis';

interface ProviderStatusStripProps {
  providers?: ProviderOutcome[];
}

// Renders the per-provider outcome ledger when the result carries more than
// one provider, or when any single provider did not succeed. Single-provider
// all-OK results need no extra chrome beyond the existing UI.
export function ProviderStatusStrip({ providers }: ProviderStatusStripProps) {
  const needsStrip =
    providers &&
    providers.length > 0 &&
    (providers.length > 1 || providers.some((p) => p.status !== 'OK'));

  if (!needsStrip) return null;

  return (
    <div className="mt-6 w-full bg-navy-900/50 border border-white/10 rounded-xl p-5">
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
        Provider Results
      </p>

      <ul className="space-y-2">
        {providers.map((outcome) => {
          const ok = outcome.status === 'OK';
          const icon = ok ? ShieldCheck : outcome.status === 'FAILED' ? ShieldX : AlertTriangle;
          const Icon = icon;

          return (
            <li
              key={outcome.provider}
              className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 bg-navy-800/60 border border-white/5 rounded-lg px-3 py-2"
            >
              <Icon
                className={`${ok ? 'text-safe' : 'text-warning'} w-4 h-4 shrink-0`}
                aria-hidden
              />

              <div className="flex flex-col sm:flex-row sm:flex-1 sm:items-center gap-1 sm:gap-3 min-w-0">
                <span className="text-sm font-semibold text-gray-200 shrink-0">
                  {outcome.provider}
                </span>

                {ok ? (
                  <span className="text-xs text-gray-400 truncate">
                    {outcome.prediction || 'Result available'}
                    {typeof outcome.riskScore === 'number'
                      ? ` • ${outcome.riskScore.toFixed(1)}% risk`
                      : ''}
                  </span>
                ) : (
                  <span className="text-xs text-warning truncate">
                    {outcome.status.toLowerCase()}
                    {outcome.message ? ` — ${outcome.message}` : ''}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
