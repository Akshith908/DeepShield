import { motion } from 'motion/react';
import { getRiskColorText } from '../utils/riskUtils';

interface RiskMeterProps {
  score: number;
  level: string;
  prediction: string;
}

function formatPrediction(prediction: string): string {
  if (!prediction) {
    return 'ANALYZING';
  }

  switch (prediction) {
    case 'LIKELY_AI_GENERATED':
      return 'AI GENERATED';

    case 'LIKELY_MANIPULATED':
      return 'MANIPULATED';

    case 'LIKELY_AUTHENTIC':
      return 'LIKELY AUTHENTIC';

    case 'INCONCLUSIVE':
      return 'INCONCLUSIVE';

    default:
      return prediction
      .replace(/_/g, ' ')
      .replace('LIKELY ', '');
  }
}

export function RiskMeter({
  score,
  level,
  prediction,
}: RiskMeterProps) {
  const radius = 70;
  const circumference = 2 * Math.PI * radius;

  const safeScore = Math.min(
    Math.max(score, 0),
                             100
  );

  const strokeDashoffset =
  circumference -
  (safeScore / 100) * circumference;

  const colorClass =
  getRiskColorText(safeScore);

  const verdict =
  formatPrediction(prediction);

  return (
    <div className="flex flex-col items-center justify-center p-6">
    <div
    className={`relative flex items-center justify-center w-64 h-64 rounded-full ${colorClass}`}
    >
    {/* Background Track */}
    <svg
    className="absolute inset-0 w-full h-full transform -rotate-90 drop-shadow-xl"
    viewBox="0 0 160 160"
    >
    <circle
    cx="80"
    cy="80"
    r={radius}
    className="text-white/5"
    strokeWidth="14"
    stroke="currentColor"
    fill="transparent"
    />

    {/* Animated Value Track */}
    <motion.circle
    cx="80"
    cy="80"
    r={radius}
    strokeWidth="14"
    stroke="currentColor"
    fill="transparent"
    strokeDasharray={circumference}
    initial={{
      strokeDashoffset: circumference,
    }}
    animate={{
      strokeDashoffset,
    }}
    transition={{
      duration: 1.5,
      ease: 'easeOut',
      delay: 0.2,
    }}
    strokeLinecap="round"
    className="drop-shadow-[0_0_8px_currentColor]"
    />
    </svg>

    {/* Center Content */}
    <motion.div
    className="absolute flex flex-col items-center justify-center text-center px-5"
    initial={{
      opacity: 0,
      scale: 0.8,
    }}
    animate={{
      opacity: 1,
      scale: 1,
    }}
    transition={{
      delay: 0.8,
      duration: 0.5,
    }}
    >
    <span
    className={`text-sm font-black tracking-wider uppercase ${colorClass}`}
    >
    {verdict}
    </span>

    <span className="text-5xl font-black tracking-tighter text-white mt-2">
    {safeScore.toFixed(1)}%
    </span>

    <span className="text-xs font-bold tracking-widest uppercase mt-2 text-gray-400">
    {level} RISK SCORE
    </span>
    </motion.div>
    </div>
    </div>
  );
}
