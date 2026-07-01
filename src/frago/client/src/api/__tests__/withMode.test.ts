import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Fully mock both backend implementations so we can observe which branch
// withMode dispatches to. Unused exports stay undefined (accessed lazily).
vi.mock('../client', () => ({
  checkVSCode: vi.fn().mockResolvedValue({ available: true }),
  waitForApi: vi.fn().mockResolvedValue(undefined),
  getProjects: vi.fn().mockResolvedValue([{ id: 'http-project' }]),
}));
vi.mock('../pywebview', () => ({
  isApiReady: vi.fn().mockReturnValue('PYWEBVIEW_READY'),
  waitForPywebview: vi.fn().mockResolvedValue(undefined),
}));

import * as httpApi from '../client';
import * as pywebviewApi from '../pywebview';
import { getApiMode, isApiReady, checkVSCode, getProjects } from '../index';

function enterPywebviewMode() {
  // Minimal stub: withMode only checks for the presence of window.pywebview.api.
  (window as unknown as { pywebview?: unknown }).pywebview = { api: {} };
}
function enterHttpMode() {
  delete (window as unknown as { pywebview?: unknown }).pywebview;
}

describe('withMode dispatch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    enterHttpMode();
  });
  afterEach(enterHttpMode);

  it('getApiMode reports http when window.pywebview.api is absent', () => {
    expect(getApiMode()).toBe('http');
  });

  it('getApiMode reports pywebview when window.pywebview.api is present', () => {
    enterPywebviewMode();
    expect(getApiMode()).toBe('pywebview');
  });

  it('routes to the http implementation in http mode', async () => {
    const projects = await getProjects();
    expect(httpApi.getProjects).toHaveBeenCalledTimes(1);
    expect(projects).toEqual([{ id: 'http-project' }]);
  });

  it('routes to the pywebview implementation in pywebview mode', async () => {
    enterPywebviewMode();
    const projects = await getProjects();
    // pywebview branch for getProjects resolves to [] without hitting httpApi.
    expect(httpApi.getProjects).not.toHaveBeenCalled();
    expect(projects).toEqual([]);
  });

  it('isApiReady is hard-coded true in http mode', () => {
    expect(isApiReady()).toBe(true);
    expect(pywebviewApi.isApiReady).not.toHaveBeenCalled();
  });

  it('isApiReady delegates to the pywebview impl in pywebview mode', () => {
    enterPywebviewMode();
    expect(isApiReady()).toBe('PYWEBVIEW_READY');
    expect(pywebviewApi.isApiReady).toHaveBeenCalledTimes(1);
  });

  it('checkVSCode calls the http impl in http mode but not in pywebview mode', async () => {
    await expect(checkVSCode()).resolves.toEqual({ available: true });
    expect(httpApi.checkVSCode).toHaveBeenCalledTimes(1);

    enterPywebviewMode();
    await expect(checkVSCode()).resolves.toEqual({ available: false });
    // still only the one http-mode call
    expect(httpApi.checkVSCode).toHaveBeenCalledTimes(1);
  });

  it('re-evaluates the mode on every call (no cached branch)', async () => {
    expect(getApiMode()).toBe('http');
    enterPywebviewMode();
    expect(getApiMode()).toBe('pywebview');
    enterHttpMode();
    expect(getApiMode()).toBe('http');
  });
});
