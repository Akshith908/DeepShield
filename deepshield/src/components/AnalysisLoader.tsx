import { motion } from 'motion/react';
import { Shield } from 'lucide-react';

interface AnalysisLoaderProps {
  mediaType?: string;
  fileName?: string;
}

function getStatusMessage(mediaType?: string): string {
  if (!mediaType) {
    return 'Submitting media for analysis...';
  }

  switch (mediaType.toLowerCase()) {
    case 'image':
      return 'Submitting image for analysis...';
    case 'video':
      return 'Submitting video for analysis...';
    case 'audio':
      return 'Waiting for audio detection results...';
    default:
      return 'Submitting media for analysis...';
  }
}

export function AnalysisLoader({ mediaType, fileName }: AnalysisLoaderProps) {
  return (
    <div className="w-full max-w-2xl mx-auto mt-16 animate-in fade-in duration-700">
      <div className="text-center mb-10">
        <h2 className="text-3xl font-bold text-white mb-3">
          Analyzing Your Media
        </h2>

        <p className="text-gray-400 text-lg">
          {getStatusMessage(mediaType)}
        </p>
      </div>

      <div className="bg-navy-800/50 border border-white/10 rounded-2xl p-8 backdrop-blur-sm shadow-xl">
        {/* Animated shield spinner */}
        <div className="flex justify-center mb-8">
          <motion.div
            className="relative"
            animate={
              {
                rotate: 360,
              }
            }
            transition={
              {
                duration: 2,
                repeat: Infinity,
                repeatType: 'loop',
              }
            }
          >
            <Shield className="h-16 w-16 text-electric-blue/30" />
            <Shield className="h-16 w-16 text-electric-blue absolute inset-0 animate-pulse" />
          </motion.div>
        </div>

        {/* File info if available */}
        {fileName && (
          <div className="text-center mb-6">
            <p className="text-sm text-gray-400 truncate max-w-md mx-auto">
              <span className="text-gray-500">File:</span>
              <span className="text-gray-300 ml-1">{fileName}</span>
            </p>

            {mediaType && (
              <p className="text-xs text-gray-500 mt-1 uppercase tracking-wider">
                {mediaType}
              </p>
            )}
          </div>
        )}

        {/* Honest status message */}
        <div className="text-center space-y-3">
          <p className="text-gray-400 text-sm leading-relaxed">
            DeepShield is waiting for the detection provider's result.
            Processing time depends on the media type and external provider.
          </p>

          <div className="flex justify-center gap-2 pt-2">
            <motion.div
              className="w-2 h-2 rounded-full bg-electric-blue/50"
              animate={
                {
                  opacity: [0.3, 1, 0.3],
                }
              }
              transition={
                {
                  duration: 1.5,
                  repeat: Infinity,
                  repeatType: 'loop',
                }
              }
            />

            <motion.div
              className="w-2 h-2 rounded-full bg-cyan-accent/50"
              animate={
                {
                  opacity: [0.3, 1, 0.3],
                }
              }
              transition={
                {
                  duration: 1.5,
                  repeat: Infinity,
                  repeatType: 'loop',
                }
              }
            />

            <motion.div
              className="w-2 h-2 rounded-full bg-electric-blue/50"
              animate={
                {
                  opacity: [0.3, 1, 0.3],
                }
              }
              transition={
                {
                  duration: 1.5,
                  repeat: Infinity,
                  repeatType: 'loop',
                }
              }
            />
          </div>
        </div>
      </div>
    </div>
  );
}
