/**
 * InitWizardModal - Four-step initialization wizard
 *
 * Steps:
 * 1. Dependencies - Check/install Node.js and Claude Code
 * 2. Resources - Install commands, skills, recipes
 * 3. Auth - Configure authentication (optional)
 * 4. Complete - Finish initialization
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, CheckCircle, Circle, Loader2 } from 'lucide-react';
import { DependencyStep } from './DependencyStep';
import { ResourceStep } from './ResourceStep';
import { AuthStep } from './AuthStep';
import { CompleteStep } from './CompleteStep';
import type { InitStatus } from '../../api/client';
import { getInitStatus } from '../../api/client';

type WizardStep = 'dependencies' | 'resources' | 'auth' | 'complete';

interface InitWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onComplete: () => void;
}

const STEPS: { id: WizardStep; labelKey: string }[] = [
  { id: 'dependencies', labelKey: 'settings.init.dependencies' },
  { id: 'resources', labelKey: 'settings.init.resources' },
  { id: 'auth', labelKey: 'settings.init.auth' },
  { id: 'complete', labelKey: 'settings.init.complete' },
];

export function InitWizardModal({ isOpen, onClose, onComplete }: InitWizardModalProps) {
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
    if (isOpen) {
      loadInitStatus();
    }
  }, [isOpen]);

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
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-gray-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">{t('init.welcome')}</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
            aria-label={t('init.closeWizard')}
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Step indicators */}
        <div className="px-6 py-4 border-b border-gray-800">
          <div className="flex items-center justify-between">
            {STEPS.map((step, index) => {
              const isActive = step.id === currentStep;
              const isCompleted = stepsCompleted[step.id];
              const isPast = STEPS.findIndex((s) => s.id === currentStep) > index;

              return (
                <div key={step.id} className="flex items-center">
                  {/* Step indicator */}
                  <button
                    type="button"
                    onClick={() => setCurrentStep(step.id)}
                    className={`flex items-center gap-2 px-3 py-1 rounded-full transition-colors ${
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
                      className={`w-8 h-0.5 mx-2 ${
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
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin mb-4" />
              <p className="text-gray-400">{t('init.loadingStatus')}</p>
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <p className="text-red-400 mb-4">{error}</p>
              <button
                type="button"
                onClick={loadInitStatus}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                {t('init.retry')}
              </button>
            </div>
          ) : initStatus ? (
            <>
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
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
