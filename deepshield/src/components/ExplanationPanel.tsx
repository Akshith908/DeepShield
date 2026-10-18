import { Brain, Info, Lightbulb } from 'lucide-react';
import { AnalysisExplanation } from '../types/analysis';

interface ExplanationPanelProps {
  explanation?: AnalysisExplanation;
}

// Distinct segment colors for the contribution bar (navy theme safe).
const SEGMENT_CLASSES = [
  'bg-electric-blue',
  'bg-cyan-accent',
  'bg-safe',
  'bg-warning',
  'bg-purple-400',
  'bg-pink-400',
];

export function ExplanationPanel({ explanation }: ExplanationPanelProps) {
  if (!explanation) return null;

  const { summary, reasons, contributions, caveat } = explanation;

  // Contributions are points on the 0-100 risk scale and sum to riskScore.
  const totalPoints = contributions.reduce((sum, item) => sum + item.points, 0);

  return (
    <div className="mt-8 w-full bg-navy-900/50 border border-white/10 rounded-xl p-6">
      <div className="flex items-center gap-2 mb-4 border-b border-white/10 pb-3">
        <Brain className="h-5 w-5 text-electric-blue" />
        <h3 className="text-lg font-semibold text-white">
          Why This Verdict
        </h3>
        <span className="ml-auto text-[10px] font-bold uppercase tracking-widest text-gray-500">
          Explainable AI
        </span>
      </div>

      <p className="text-sm text-gray-300 leading-relaxed mb-5">{summary}</p>

      {contributions.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
            Score Composition
          </p>

          {/* Stacked contribution bar over the full 0-100 risk scale */}
          <div className="w-full h-3 rounded-full bg-white/5 overflow-hidden flex">
            {contributions.map((item, index) => (
              <div
                key={`${item.name}-${index}`}
                className={`h-full ${SEGMENT_CLASSES[index % SEGMENT_CLASSES.length]} transition-all duration-700`}
                style={{ width: `${Math.min(Math.max(item.points, 0), 100)}%` }}
                title={`${item.name}: +${item.points.toFixed(1)} pts`}
              />
            ))}
          </div>

          <div className="mt-3 space-y-2">
            {contributions.map((item, index) => (
              <div
                key={`${item.name}-row-${index}`}
                className="flex items-center gap-3 text-sm bg-navy-800/60 border border-white/5 rounded-lg px-3 py-2"
              >
                <span
                  className={`h-2.5 w-2.5 rounded-full shrink-0 ${
                    SEGMENT_CLASSES[index % SEGMENT_CLASSES.length]
                  }`}
                />

                <span className="text-gray-200 truncate">{item.name}</span>

                <span className="text-gray-500 text-xs truncate hidden sm:inline">
                  {item.value}
                </span>

                <span className="ml-auto font-mono text-xs text-gray-300 shrink-0">
                  {item.score.toFixed(1)}% → +{item.points.toFixed(1)}
                </span>
              </div>
            ))}
          </div>

          <p className="mt-2 text-xs text-gray-500">
            Detection scores allocated across the{' '}
            <span className="font-mono">{totalPoints.toFixed(1)}</span>-point risk
            score, proportional to each signal's evidence strength. These are
            evidence contributions, not definitive causal explanations: they
            show how the score was composed, not why the underlying models
            reached their verdicts.
          </p>
        </div>
      )}

      {reasons.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">
            Decision Rationale
          </p>

          <ul className="space-y-2">
            {reasons.map((reason, index) => (
              <li key={index} className="flex items-start gap-2 text-sm text-gray-300 leading-relaxed">
                <Lightbulb className="h-4 w-4 mt-0.5 text-cyan-accent shrink-0" />
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {caveat && (
        <div className="flex items-start gap-3 bg-white/5 border border-warning/30 rounded-lg px-4 py-3">
          <Info className="h-4 w-4 mt-0.5 text-warning shrink-0" />

          <p className="text-xs text-gray-400 leading-relaxed">{caveat}</p>
        </div>
      )}
    </div>
  );
}