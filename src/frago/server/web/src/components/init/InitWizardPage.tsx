/**
 * InitWizardPage - Full-screen standalone initialization wizard
 *
 * This is a complete page (not a modal) that guides users through initial setup.
 * Replaces the modal-based wizard for a cleaner, more focused experience.
 *
 * Steps:
 * 1. Dependencies - Check/install Node.js and Claude Code
 * 2. Resources - Install commands, skills, recipes
 * 3. Auth - Configure authentication (optional)
 * 4. Complete - Finish initialization
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle, Circle, Loader2 } from 'lucide-react';
import { DependencyStep } from './DependencyStep';
import { ResourceStep } from './ResourceStep';
import { AuthStep } from './AuthStep';
import { CompleteStep } from './CompleteStep';
import type { InitStatus } from '../../api/client';
import { getInitStatus } from '../../api/client';

type WizardStep = 'dependencies' | 'resources' | 'auth' | 'complete';

interface InitWizardPageProps {
  onComplete: () => void;
}

const STEPS: { id: WizardStep; labelKey: string }[] = [
  { id: 'dependencies', labelKey: 'settings.init.dependencies' },
  { id: 'resources', labelKey: 'settings.init.resources' },
  { id: 'auth', labelKey: 'settings.init.auth' },
  { id: 'complete', labelKey: 'settings.init.complete' },
];

export function InitWizardPage({ onComplete }: InitWizardPageProps) {
  const { t } = useTranslation();
  const [currentStep, setCurrentStep] = useState<WizardStep>('dependencies');
  const [initStatus, setInitStatus] = useState<InitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track step completion status
  const [stepsCompleted, setStepsCompleted] = useState({
    dependencies: false,
    resources: false,
    auth: false,
    complete: false,
  });

  // Load init status on mount
  useEffect(() => {
    loadInitStatus();
  }, []);

  const loadInitStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const status = await getInitStatus();
      setInitStatus(status);

      // Update step completion based on status
      const depsSatisfied =
        status.node.installed &&
        status.node.version_sufficient &&
        status.claude_code.installed &&
        status.claude_code.version_sufficient;

      setStepsCompleted((prev) => ({
        ...prev,
        dependencies: depsSatisfied,
        resources: status.resources_installed,
        auth: status.auth_configured,
      }));

      // Auto-advance to first incomplete step
      if (depsSatisfied && !status.resources_installed) {
        setCurrentStep('resources');
      } else if (depsSatisfied && status.resources_installed && !status.auth_configured) {
        setCurrentStep('auth');
      } else if (depsSatisfied && status.resources_installed) {
        setCurrentStep('complete');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load init status');
    } finally {
      setLoading(false);
    }
  };

  const handleStepComplete = (step: WizardStep) => {
    setStepsCompleted((prev) => ({ ...prev, [step]: true }));

    // Auto-advance to next step
    const stepIndex = STEPS.findIndex((s) => s.id === step);
    if (stepIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[stepIndex + 1].id);
    }
  };

  const handleSkip = () => {
    const stepIndex = STEPS.findIndex((s) => s.id === currentStep);
    if (stepIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[stepIndex + 1].id);
    }
  };

  const handleBack = () => {
    const stepIndex = STEPS.findIndex((s) => s.id === currentStep);
    if (stepIndex > 0) {
      setCurrentStep(STEPS[stepIndex - 1].id);
    }
  };

  const handleComplete = () => {
    onComplete();
  };

  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-4">
      <div className="w-full max-w-4xl">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">{t('init.welcome')}</h1>
          <p className="text-gray-400">{t('init.setupGuide')}</p>
        </div>

        {/* Main wizard card */}
        <div className="bg-gray-900 rounded-xl shadow-2xl overflow-hidden">
          {/* Step indicators */}
          <div className="px-8 py-6 border-b border-gray-800">
            <div className="flex items-center justify-between max-w-2xl mx-auto">
              {STEPS.map((step, index) => {
                const isActive = step.id === currentStep;
                const isCompleted = stepsCompleted[step.id];
                const isPast = STEPS.findIndex((s) => s.id === currentStep) > index;

                return (
                  <div key={step.id} className="flex items-center flex-1">
                    {/* Step indicator */}
                    <button
                      type="button"
                      onClick={() => setCurrentStep(step.id)}
                      className={`flex items-center gap-2 px-4 py-2 rounded-full transition-colors whitespace-nowrap ${
                        isActive
                          ? 'bg-blue-600 text-white'
                          : isCompleted || isPast
                            ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                            : 'bg-gray-800 text-gray-500'
                      }`}
                    >
                      {isCompleted ? (
                        <CheckCircle className="w-4 h-4 text-green-400" />
                      ) : (
                        <Circle className="w-4 h-4" />
                      )}
                      <span className="text-sm font-medium">{t(step.labelKey)}</span>
                    </button>

                    {/* Connector line */}
                    {index < STEPS.length - 1 && (
                      <div
                        className={`flex-1 h-0.5 mx-3 ${
                          isPast || isCompleted ? 'bg-blue-600' : 'bg-gray-700'
                        }`}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Content */}
          <div className="p-8 min-h-[500px]">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-20">
                <Loader2 className="w-12 h-12 text-blue-500 animate-spin mb-4" />
                <p className="text-gray-400">{t('init.loadingStatus')}</p>
              </div>
            ) : error ? (
              <div className="text-center py-20">
                <p className="text-red-400 mb-4 text-lg">{error}</p>
                <button
                  type="button"
                  onClick={loadInitStatus}
                  className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                >
                  {t('init.retry')}
                </button>
              </div>
            ) : initStatus ? (
              <div className="max-w-2xl mx-auto">
                {currentStep === 'dependencies' && (
                  <DependencyStep
                    initStatus={initStatus}
                    onComplete={() => handleStepComplete('dependencies')}
                    onSkip={handleSkip}
                    onRefresh={loadInitStatus}
                  />
                )}
                {currentStep === 'resources' && (
                  <ResourceStep
                    initStatus={initStatus}
                    onComplete={() => handleStepComplete('resources')}
                    onSkip={handleSkip}
                    onBack={handleBack}
                    onRefresh={loadInitStatus}
                  />
                )}
                {currentStep === 'auth' && (
                  <AuthStep
                    initStatus={initStatus}
                    onComplete={() => handleStepComplete('auth')}
                    onSkip={handleSkip}
                    onBack={handleBack}
                  />
                )}
                {currentStep === 'complete' && (
                  <CompleteStep
                    initStatus={initStatus}
                    stepsCompleted={stepsCompleted}
                    onComplete={handleComplete}
                    onBack={handleBack}
                  />
                )}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
