import { useRef, useState } from 'react';
import { Navbar } from './components/Navbar';
import { UploadZone } from './components/UploadZone';
import { FilePreview } from './components/FilePreview';
import { AnalysisLoader } from './components/AnalysisLoader';
import { RiskMeter } from './components/RiskMeter';
import { ResultSummary } from './components/ResultSummary';
import { SecurityRecommendation } from './components/SecurityRecommendation';
import { AnalysisDetails } from './components/AnalysisDetails';
import { MediaDetails } from './components/MediaDetails';
import { ErrorMessage } from './components/ErrorMessage';
import { analyzeMedia } from './services/analysisService';
import { AnalysisResult } from './types/analysis';
import { motion } from 'motion/react';
import { RefreshCcw } from 'lucide-react';

type AppState =
| 'UPLOAD'
| 'ANALYZING'
| 'RESULTS'
| 'ERROR';

export default function App() {
  const [appState, setAppState] =
  useState<AppState>('UPLOAD');

  const [selectedFile, setSelectedFile] =
  useState<File | null>(null);

  const [result, setResult] =
  useState<AnalysisResult | null>(null);

  const [error, setError] =
  useState<string | null>(null);

  // Use ref for synchronous duplicate submission prevention
  // React state updates are async, so isAnalyzing state alone
  // doesn't prevent rapid double-submissions before re-render
  const isAnalyzingRef = useRef(false);

  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setError(null);
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setError(null);
  };

  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAnalyze = async () => {
    // Check ref first for immediate synchronous guard
    if (!selectedFile || isAnalyzingRef.current) return;

    // Set both ref and state to prevent duplicate submissions
    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setAppState('ANALYZING');
    setError(null);

    try {
      const analysisResult =
      await analyzeMedia(selectedFile);

      setResult(analysisResult);
      setAppState('RESULTS');
    } catch (err: unknown) {
      console.error(
        'Analysis failed:',
        err
      );

      const message =
      err instanceof Error
      ? err.message
      : 'An unexpected error occurred during analysis.';

      setError(message);
      setAppState('ERROR');
    } finally {
      isAnalyzingRef.current = false;
      setIsAnalyzing(false);
    }
  };

  const handleReset = () => {
    setAppState('UPLOAD');
    setSelectedFile(null);
    setResult(null);
    setError(null);
  };

  return (
    <div className="min-h-screen flex flex-col bg-navy-900 selection:bg-electric-blue/30">

    {/* Background ambient glows */}
    <div className="fixed inset-0 overflow-hidden pointer-events-none">
    <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] rounded-full bg-electric-blue/5 blur-[120px]" />

    <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-cyan-accent/5 blur-[120px]" />
    </div>

    <Navbar />

    <main className="flex-grow container mx-auto px-4 py-8 flex flex-col items-center relative z-10">

    {/* =========================
      STATE: UPLOAD
      ========================= */}
      {appState === 'UPLOAD' && (
        <motion.div
        initial={{
          opacity: 0,
          y: 20,
        }}
        animate={{
          opacity: 1,
          y: 0,
        }}
        className="w-full flex flex-col items-center mt-12"
        >

        <div className="text-center max-w-3xl mx-auto px-4">

        <h1 className="text-4xl md:text-5xl lg:text-6xl font-black text-white tracking-tight mb-6">
        Can You Trust{' '}

        <span className="text-transparent bg-clip-text bg-gradient-to-r from-electric-blue to-cyan-accent">
        What You See?
        </span>
        </h1>

        <p className="text-lg md:text-xl text-gray-400 max-w-2xl mx-auto leading-relaxed">
        Analyze suspicious images, videos, and audio for
        potential AI-generated or manipulated content before
        you trust, share, or act on them.
        </p>

        </div>

        {!selectedFile ? (
          <UploadZone
          onFileSelect={handleFileSelect}
          />
        ) : (
          <FilePreview
          file={selectedFile}
          onRemove={handleRemoveFile}
          onAnalyze={handleAnalyze}
          />
        )}

        </motion.div>
      )}

      {/* =========================
        STATE: ANALYZING
        ========================= */}
        {appState === 'ANALYZING' && (
          <AnalysisLoader
            mediaType={selectedFile?.type?.split('/')[0]}
            fileName={selectedFile?.name}
          />
        )}

        {/* =========================
          STATE: ERROR
          ========================= */}
          {appState === 'ERROR' && error && (
            <ErrorMessage
            message={error}
            onRetry={handleReset}
            />
          )}

          {/* =========================
            STATE: RESULTS
            ========================= */}
            {appState === 'RESULTS' && result && (
              <motion.div
              initial={{
                opacity: 0,
                scale: 0.95,
              }}
              animate={{
                opacity: 1,
                scale: 1,
              }}
              transition={{
                duration: 0.5,
              }}
              className="w-full max-w-4xl mx-auto mt-8 mb-16"
              >

              <div className="bg-navy-800/80 border border-white/10 rounded-3xl p-6 md:p-10 backdrop-blur-md shadow-2xl">

              <div className="text-center mb-6">

              <h2 className="text-sm font-bold tracking-[0.2em] text-gray-400 uppercase mb-2">
              AI Manipulation Risk Assessment
              </h2>

              </div>

              {/* Main verdict + risk score */}
              <RiskMeter
              score={result.riskScore}
              level={result.riskLevel}
              prediction={result.prediction}
              />

              {/* Human-readable explanation */}
              <ResultSummary
              score={result.riskScore}
              prediction={result.prediction}
              />

              {/* Security advice */}
              <SecurityRecommendation
              score={result.riskScore}
              recommendation={result.recommendation}
              />

              <div className="mt-8 grid grid-cols-1 gap-8">

              {/* Individual detection signals */}
              <AnalysisDetails
              signals={result.signals}
              />

              {/* File and analysis metadata */}
              <MediaDetails
              result={result}
              />

              </div>

              <div className="mt-12 flex flex-col items-center gap-6">

              <button
              onClick={handleReset}
              className="flex items-center gap-2 px-8 py-3.5 bg-white/5 border border-white/10 text-white font-medium rounded-lg hover:bg-white/10 transition-colors"
              >
              <RefreshCcw className="h-4 w-4" />

              Analyze Another File
              </button>

              <p className="text-xs text-gray-500 text-center max-w-lg leading-relaxed">
              DeepShield provides an automated risk assessment and
              should not be considered definitive proof of
              authenticity or manipulation.
              </p>

              </div>

              </div>

              </motion.div>
            )}

            </main>

            </div>
  );
}
