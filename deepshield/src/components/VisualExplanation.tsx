import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Fingerprint,
  Info,
  Layers,
  Loader2,
  ScanSearch,
  Sparkles,
} from 'lucide-react';
import { explainImage } from '../services/analysisService';
import { VisualExplanation as VisualExplanationResult } from '../types/analysis';

interface VisualExplanationProps {
  file: File;
}

// Required disclaimer, reproduced verbatim.
export const GRADCAM_DISCLAIMER =
  "Local model explanation: This heatmap highlights regions influencing the local model's prediction. It does not prove that those regions are manipulated and may not explain the verdict returned by an external detection provider.";

type Phase = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Optional Grad-CAM section for image results.
 *
 * It lives beside the provider verdict and never replaces it: its own model,
 * its own prediction, its own failure state. Nothing is fetched until the user
 * asks, and a failed generation renders no heatmap at all.
 */
export function VisualExplanation({ file }: VisualExplanationProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<VisualExplanationResult | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [opacity, setOpacity] = useState(60);
  const [layout, setLayout] = useState<'overlay' | 'compare'>('overlay');
  const [originalUrl, setOriginalUrl] = useState('');

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setOriginalUrl(url);

    return () => URL.revokeObjectURL(url);
  }, [file]);

  // A new file resets the panel: an old heatmap must never be shown for a
  // different image.
  useEffect(() => {
    setPhase('idle');
    setResult(null);
    setError(null);
  }, [file]);

  const run = async () => {
    setPhase('loading');
    setError(null);
    setResult(null);

    try {
      const explanation = await explainImage(file);
      setResult(explanation);
      setPhase('ready');
    } catch (err) {
      setError({
        code: err && typeof err === 'object' && 'code' in err ? String(err.code) : 'unknown',
        message:
          err instanceof Error
            ? err.message
            : 'The visual explanation could not be generated.',
      });
      setPhase('error');
    }
  };

  return (
    <div className="mt-8 w-full bg-navy-900/50 border border-white/10 rounded-xl p-6">
      <div className="flex flex-wrap items-center gap-2 mb-4 border-b border-white/10 pb-3">
        <ScanSearch className="h-5 w-5 text-electric-blue" />
        <h3 className="text-lg font-semibold text-white">Visual Explanation</h3>
        <span className="ml-auto text-[10px] font-bold uppercase tracking-widest text-gray-500">
          Local model &middot; Grad-CAM
        </span>
      </div>

      {phase === 'idle' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-300 leading-relaxed">
            Show which regions of this image influenced the prediction of a
            local EfficientNet-B4 deepfake detector. This runs separately from
            the BitMind analysis above and does not change its verdict or risk
            score.
          </p>

          <button
            onClick={run}
            className="flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-navy-900 bg-electric-blue rounded-lg hover:bg-cyan-accent transition-colors"
          >
            <Sparkles className="h-4 w-4" />
            Generate Visual Explanation
          </button>
        </div>
      )}

      {phase === 'loading' && (
        <div className="flex items-center gap-3 py-4 text-sm text-gray-300" role="status">
          <Loader2 className="h-4 w-4 animate-spin text-electric-blue" />
          Running the local model and computing Grad-CAM&hellip;
        </div>
      )}

      {phase === 'error' && error && (
        <div className="space-y-4" role="alert">
          <div className="flex items-start gap-3 bg-danger/10 border border-danger/30 rounded-lg px-4 py-3">
            <AlertTriangle className="h-4 w-4 mt-0.5 text-danger shrink-0" />
            <div className="space-y-1">
              <p className="text-sm text-gray-200">{error.message}</p>
              <p className="text-xs text-gray-500">
                No heatmap is shown when generation fails. The provider result
                above is unaffected.
              </p>
            </div>
          </div>

          <button
            onClick={run}
            className="px-4 py-2 text-sm font-medium text-white bg-white/5 border border-white/10 rounded-lg hover:bg-white/10 transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {phase === 'ready' && result && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={`px-3 py-1 rounded-full text-xs font-bold tracking-wide ${
                result.localPrediction === 'FAKE'
                  ? 'bg-danger/15 text-danger border border-danger/30'
                  : 'bg-safe/15 text-safe border border-safe/30'
              }`}
            >
              Local model: {result.localPrediction}
            </span>

            <span className="text-xs text-gray-400">
              {result.localConfidence.toFixed(1)}% confidence
              <span className="text-gray-600"> · </span>
              {result.fakeProbability.toFixed(1)}% fake probability
            </span>

            <span className="text-xs text-gray-500 ml-auto font-mono">
              {result.processingTime.toFixed(2)}s
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs text-gray-500">
            <Fingerprint className="h-3.5 w-3.5" />
            <span className="font-mono break-all">{result.modelId}</span>
            <span className="text-gray-600">·</span>
            <Layers className="h-3.5 w-3.5" />
            <span className="font-mono">{result.gradcamLayer}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setLayout('overlay')}
              aria-pressed={layout === 'overlay'}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                layout === 'overlay'
                  ? 'bg-electric-blue text-navy-900'
                  : 'bg-white/5 text-gray-300 hover:bg-white/10'
              }`}
            >
              Overlay
            </button>
            <button
              onClick={() => setLayout('compare')}
              aria-pressed={layout === 'compare'}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                layout === 'compare'
                  ? 'bg-electric-blue text-navy-900'
                  : 'bg-white/5 text-gray-300 hover:bg-white/10'
              }`}
            >
              Side by side
            </button>
          </div>

          {layout === 'overlay' ? (
            <div className="space-y-3">
              <div className="relative rounded-lg overflow-hidden border border-white/10 bg-black/40">
                <img
                  src={originalUrl}
                  alt="Original upload"
                  className="w-full h-auto block"
                />
                <img
                  src={result.overlay}
                  alt="Grad-CAM heatmap blended over the original image"
                  className="absolute inset-0 w-full h-full object-fill"
                  style={{ opacity: opacity / 100 }}
                />
              </div>

              <label className="flex items-center gap-3 text-xs text-gray-400">
                <span className="shrink-0">Heatmap opacity</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={opacity}
                  aria-label="Heatmap opacity"
                  onChange={(event) => setOpacity(Number(event.target.value))}
                  className="w-full accent-electric-blue"
                />
                <span className="w-9 text-right font-mono text-gray-300">{opacity}%</span>
              </label>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { src: originalUrl, label: 'Original' },
                { src: result.heatmap, label: 'Grad-CAM heatmap' },
                { src: result.overlay, label: 'Overlay' },
              ].map((panel) => (
                <figure
                  key={panel.label}
                  className="rounded-lg overflow-hidden border border-white/10 bg-black/40"
                >
                  <img src={panel.src} alt={panel.label} className="w-full h-auto block" />
                  <figcaption className="text-[10px] uppercase tracking-wider text-gray-500 px-2 py-1.5 border-t border-white/10">
                    {panel.label}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}

          {result.limitations.length > 0 && (
            <ul className="space-y-1.5">
              {result.limitations.map((limitation) => (
                <li key={limitation} className="flex items-start gap-2 text-xs text-gray-500 leading-relaxed">
                  <Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-gray-600" />
                  <span>{limitation}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="mt-5 text-xs text-gray-500 leading-relaxed border-t border-white/10 pt-4">
        {GRADCAM_DISCLAIMER}
      </p>
    </div>
  );
}
