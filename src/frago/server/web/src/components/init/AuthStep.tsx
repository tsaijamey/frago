/**
 * AuthStep - Configure authentication method
 *
 * Simplified step that links to the full settings page for auth configuration.
 */

import { useState } from 'react';
import {
  CheckCircle,
  ArrowRight,
  ArrowLeft,
  Settings,
  Key,
  Shield,
} from 'lucide-react';
import type { InitStatus } from '../../api/client';

interface AuthStepProps {
  initStatus: InitStatus;
  onComplete: () => void;
  onSkip: () => void;
  onBack: () => void;
}

export function AuthStep({
  initStatus,
  onComplete,
  onSkip,
  onBack,
}: AuthStepProps) {
  const [acknowledged, setAcknowledged] = useState(false);

  const authConfigured = initStatus.auth_configured;
  const authMethod = initStatus.auth_method;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-white mb-2">
          Authentication Setup
        </h3>
        <p className="text-gray-400">
          Configure how Claude Code authenticates with Anthropic or a third-party API.
        </p>
      </div>

      {/* Current status */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-3">
          {authConfigured ? (
            <CheckCircle className="w-5 h-5 text-green-400" />
          ) : (
            <Shield className="w-5 h-5 text-gray-500" />
          )}
          <div>
            <h4 className="font-medium text-white">Authentication Status</h4>
            <p className="text-sm text-gray-400">
              {authConfigured
                ? `Configured: ${authMethod === 'official' ? 'Official (user-managed)' : 'Custom API endpoint'}`
                : 'Not configured'}
            </p>
          </div>
        </div>
      </div>

      {/* Auth options explanation */}
      <div className="space-y-4">
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <div className="flex items-start gap-3">
            <Key className="w-5 h-5 text-blue-400 mt-0.5" />
            <div>
              <h4 className="font-medium text-white">Official Authentication</h4>
              <p className="text-sm text-gray-400 mt-1">
                Use Anthropic's official authentication. You manage your own Claude login.
                This is the default and recommended option for most users.
              </p>
            </div>
          </div>
        </div>

        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <div className="flex items-start gap-3">
            <Settings className="w-5 h-5 text-purple-400 mt-0.5" />
            <div>
              <h4 className="font-medium text-white">Custom API Endpoint</h4>
              <p className="text-sm text-gray-400 mt-1">
                Connect to a third-party API endpoint (DeepSeek, Aliyun, Kimi, etc.)
                with your own API key. Configure this in Settings after setup.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Acknowledgment for skipping */}
      {!authConfigured && (
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-400">
            I'll configure authentication later in Settings
          </span>
        </label>
      )}

      {/* Info note */}
      <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg p-4 text-sm text-blue-300">
        <p>
          <strong>Note:</strong> You can change authentication settings anytime from the
          Settings page. If using official authentication, make sure to log in to Claude
          Code via terminal first.
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-4 border-t border-gray-800">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-2 text-gray-400 hover:text-gray-300"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSkip}
            className="text-gray-400 hover:text-gray-300 text-sm"
          >
            Skip
          </button>

          <button
            type="button"
            onClick={onComplete}
            disabled={!authConfigured && !acknowledged}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Continue
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
