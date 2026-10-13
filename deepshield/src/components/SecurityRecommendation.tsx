import { ShieldAlert, ShieldCheck, AlertTriangle } from 'lucide-react';
import { getRiskColorText, getRiskColorBg, getRiskColorBorder } from '../utils/riskUtils';

interface SecurityRecommendationProps {
  score: number;
  recommendation: string;
}

export function SecurityRecommendation({ score, recommendation }: SecurityRecommendationProps) {
  const textColor = getRiskColorText(score);
  const bgColor = getRiskColorBg(score);
  const borderColor = getRiskColorBorder(score);
  
  const Icon = score < 30 ? ShieldCheck : score < 70 ? AlertTriangle : ShieldAlert;

  return (
    <div className={`mt-8 p-6 rounded-xl border ${borderColor} bg-navy-900/40 relative overflow-hidden`}>
      {/* Subtle background tint based on risk */}
      <div className={`absolute inset-0 opacity-10 ${bgColor}`} />
      
      <div className="relative z-10 flex items-start gap-4">
        <div className={`p-3 rounded-full ${bgColor} bg-opacity-20`}>
          <Icon className={`h-6 w-6 ${textColor}`} />
        </div>
        <div>
          <h4 className={`text-base font-bold uppercase tracking-wider mb-2 ${textColor}`}>
            Recommended Action
          </h4>
          <p className="text-gray-300 leading-relaxed text-sm md:text-base">
            {recommendation}
          </p>
        </div>
      </div>
    </div>
  );
}
