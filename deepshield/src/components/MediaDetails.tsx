import { AnalysisResult } from '../types/analysis';
import {
  File,
  Clock,
  HardDrive,
  Type,
  ShieldCheck,
} from 'lucide-react';

interface MediaDetailsProps {
  result: AnalysisResult;
}

export function MediaDetails({
  result,
}: MediaDetailsProps) {
  return (
    <div className="w-full mt-8">
    <h3 className="text-lg font-semibold text-white mb-4 border-b border-white/10 pb-2">
    Media Details
    </h3>

    <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
    {/* Media Type */}
    <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
    <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
    <Type className="h-3.5 w-3.5" />
    Media Type
    </div>

    <span className="text-gray-200 capitalize font-medium">
    {result.mediaType}
    </span>
    </div>

    {/* Format */}
    <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
    <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
    <File className="h-3.5 w-3.5" />
    Format
    </div>

    <span className="text-gray-200 font-medium">
    {result.format || 'Unknown'}
    </span>
    </div>

    {/* File Size */}
    <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
    <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
    <HardDrive className="h-3.5 w-3.5" />
    File Size
    </div>

    <span className="text-gray-200 font-medium">
    {result.fileSize || 'N/A'}
    </span>
    </div>

    {/* Server Processing Time (e.g. upload handling, provider call,
        normalization; measured server-side) */}
    <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
    <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
    <Clock className="h-3.5 w-3.5" />
    Server Processing Time
    </div>

    <span className="text-gray-200 font-medium">
    {typeof result.analysisTime === 'number'
      ? `${result.analysisTime.toFixed(2)}s`
      : 'N/A'}
      </span>
      </div>

      {/* Total Analysis Time (client-measured from the Analyze click through
          result delivery; includes upload transit and backend wait) */}
      <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
      <Clock className="h-3.5 w-3.5" />
      Total Analysis Time
      </div>

      <span className="text-gray-200 font-medium">
      {typeof result.totalTime === 'number'
        ? `${(result.totalTime / 1000).toFixed(2)}s`
        : 'N/A'}
        </span>
        </div>

      {/* Confidence */}
      <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
      <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
      <ShieldCheck className="h-3.5 w-3.5" />
      Confidence
      </div>

      <span className="text-gray-200 font-medium">
      {result.confidence || 'N/A'}
      </span>
      </div>

      {/* Optional Duration */}
      {result.duration !== undefined && (
        <div className="bg-navy-900/50 rounded-lg p-4 border border-white/5 flex flex-col gap-2">
        <div className="flex items-center gap-2 text-gray-500 text-xs font-semibold uppercase tracking-wider">
        <Clock className="h-3.5 w-3.5" />
        Duration
        </div>

        <span className="text-gray-200 font-medium">
        {result.duration.toFixed(1)}s
        </span>
        </div>
      )}
      </div>
      </div>
  );
}
