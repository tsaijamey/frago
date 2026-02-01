/**
 * InitWizardModal - Five-step initialization wizard
 *
 * Steps:
 * 1. Core - Select core type (Claude Code vs OpenCode)
 * 2. Client - Check/install the corresponding client
 * 3. Auth - Select authentication method
 * 4. Resources - Install commands, skills, recipes
 * 5. Complete - Finish initialization
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X, CheckCircle, Circle, Loader2 } from 'lucide-react';
import { CoreSelectionStep } from './CoreSelectionStep';
import { DependencyStep } from './DependencyStep';
import { AuthMethodStep } from './AuthMethodStep';
import { ResourceStep } from './ResourceStep';
import { CompleteStep } from './CompleteStep';
import type { InitStatus } from '../../api/client';
import { getInitStatus, updateAuth } from '../../api/client';

type WizardStep = 'core' | 'client' | 'auth' | 'resources' | 'complete';
type CoreType = 'claude-code' | 'opencode' | null;

interface InitWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onComplete: () => void;
}

export function InitWizardModal({ isOpen, onClose, onComplete }: InitWizardModalProps) {
  const { t } = useTranslation();
  const [currentStep, setCurrentStep] = useState<WizardStep>('core');
  const [initStatus, setInitStatus] = useState<InitStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [coreType, setCoreType] = useState<CoreType>(null);

  // Track step completion status
  const [stepsCompleted, setStepsCompleted] = useState({
    core: false,
    client: false,
    auth: false,
    resources: false,
    complete: false,
  });

  // Dynamic step configuration based on core type
  const getStepLabel = (stepId: WizardStep): string => {
    if (stepId === 'client') {
      return coreType === 'opencode' ? 'OpenCode' : 'Claude';
    }
    const labelKeys: Record<WizardStep, string> = {
      core: 'settings.init.core',
      client: 'settings.init.claude',
      auth: 'settings.init.auth',
      resources: 'settings.init.resources',
      complete: 'settings.init.complete',
    };
    return t(labelKeys[stepId]);
  };

  const STEPS: WizardStep[] = ['core', 'client', 'auth', 'resources', 'complete'];

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

      const claudeSatisfied =
        status.claude_code.installed &&
        status.claude_code.version_sufficient;

      const authConfigured = status.auth_configured;

      setStepsCompleted((prev) => ({
        ...prev,
        client: claudeSatisfied,
        auth: authConfigured,
        resources: status.resources_installed,
      }));

      if (authConfigured && claudeSatisfied && status.resources_installed) {
        setCoreType('claude-code');
        setStepsCompleted(prev => ({ ...prev, core: true }));
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

    const stepIndex = STEPS.indexOf(step);
    if (stepIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[stepIndex + 1]);
    }
  };

  const handleCoreSelectionComplete = (selectedCoreType: 'claude-code' | 'opencode') => {
    setCoreType(selectedCoreType);
    handleStepComplete('core');
  };

  const handleAuthMethodComplete = async (authMethod: 'official' | 'custom', endpointType?: string) => {
    try {
      if (authMethod === 'official') {
        await updateAuth({ auth_method: 'official' });
      } else if (authMethod === 'custom' && endpointType) {
        await updateAuth({
          auth_method: 'custom',
          api_endpoint: {
            type: endpointType,
            api_key: '',
          },
        });
      }
    } catch (err) {
      console.error('Failed to save auth configuration:', err);
    }

    handleStepComplete('auth');
  };

  const handleSkip = () => {
    const stepIndex = STEPS.indexOf(currentStep);
    if (stepIndex < STEPS.length - 1) {
      setCurrentStep(STEPS[stepIndex + 1]);
    }
  };

  const handleBack = () => {
    const stepIndex = STEPS.indexOf(currentStep);
    if (stepIndex > 0) {
      setCurrentStep(STEPS[stepIndex - 1]);
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
          <h2 className="text-xl font-semibold text-white font-mono">{t('init.welcome')}</h2>
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
              const isActive = step === currentStep;
              const isCompleted = stepsCompleted[step];
              const isPast = STEPS.indexOf(currentStep) > index;

              return (
                <div key={step} className="flex items-center">
                  <button
                    type="button"
                    onClick={() => {
                      if (isCompleted || isPast) {
                        setCurrentStep(step);
                      }
                    }}
                    disabled={!isCompleted && !isPast && !isActive}
                    className={`flex items-center gap-2 px-3 py-1 rounded-full transition-colors font-mono ${
                      isActive
                        ? 'bg-green-600 text-white'
                        : isCompleted || isPast
                          ? 'bg-gray-700 text-gray-300 hover:bg-gray-600 cursor-pointer'
                          : 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    }`}
                  >
                    {isCompleted ? (
                      <CheckCircle className="w-4 h-4 text-green-400" />
                    ) : (
                      <Circle className="w-4 h-4" />
                    )}
                    <span className="text-sm font-medium">{getStepLabel(step)}</span>
                  </button>

                  {index < STEPS.length - 1 && (
                    <div
                      className={`w-8 h-0.5 mx-2 ${
                        isPast || isCompleted ? 'bg-green-600' : 'bg-gray-700'
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
              <Loader2 className="w-8 h-8 text-green-500 animate-spin mb-4" />
              <p className="text-gray-400 font-mono">{t('init.loadingStatus')}</p>
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <p className="text-red-400 mb-4 font-mono">{error}</p>
              <button
                type="button"
                onClick={loadInitStatus}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-mono"
              >
                {t('init.retry')}
              </button>
            </div>
          ) : initStatus ? (
            <>
              {currentStep === 'core' && (
                <CoreSelectionStep
                  onComplete={handleCoreSelectionComplete}
                  onSkip={handleSkip}
                />
              )}
              {currentStep === 'client' && (
                <DependencyStep
                  initStatus={initStatus}
                  onComplete={() => handleStepComplete('client')}
                  onSkip={handleSkip}
                  onRefresh={loadInitStatus}
                />
              )}
              {currentStep === 'auth' && coreType && (
                <AuthMethodStep
                  coreType={coreType}
                  onComplete={handleAuthMethodComplete}
                  onBack={handleBack}
                  onSkip={handleSkip}
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
