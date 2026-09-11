/**
 * EnvironmentModal —— 跑 frago 需要的那一整套东西，齐不齐、要不要你动手。
 *
 * **每一格第一眼看到的是一句结论，不是版本号。** 上一版把 `2.50.1` 和 `最新 2.55.0`
 * 并排摆在最显眼的位置，结果是人读完两个数字仍然不知道这要不要紧——差一个小版本和
 * 缺一样必需的东西长得一模一样。现在第一行直接写「没事」「有新版」「没装」，版本号
 * 退成底下一行小字，谁想核对谁去看。
 *
 * **颜色只留给真的要人动手的那几格。** 从前只要有新版就整格染成琥珀色，一屏十几格
 * 全亮着，看着像机器坏了一半，实际上一样都不影响用。现在有新版的那几格是安静的，
 * 只有「缺了必需的东西」和「升级没成、得你自己来」才上色。
 *
 * **人要做的事写成他能照做的样子。** 升级被本机规则拦下时，worker 把该由人执行的那条
 * 命令原样交回来，格子里直接摆出来并配一颗复制按钮——而不是丢一句「被拦截了」让人
 * 自己猜下一步。
 *
 * **这张清单照装机向导抄，不是这里现编的。** 装机时探测脚本查哪几样，这张表就报哪
 * 几样，再加上 frago 自己。两处对不上，用户装完看到的和事后查到的就成了两台机器。
 *
 * **只有关闭按钮能关掉它。** 点周围收窗对一张要来回对照着读的表是个陷阱：人的视线在
 * 十几格之间移动，鼠标跟着落到格与格的空隙上，一点就没了。升级跑着的时候更是如此。
 *
 * **默认每行四格**，屏幕窄下去依次退到三格、两格、一格。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUp, Check, Copy, Loader2, RefreshCw, X } from 'lucide-react';
import type { EnvironmentState, EnvironmentUpgradeState } from '@/hooks/useEnvironment';
import type { EnvironmentItem, EnvironmentUpgradeItemState } from '@/types/api';

interface Props {
  /** 版本表与升级进度都由左栏那颗按钮持有——它比这扇窗活得久，关窗不丢状态 */
  environment: EnvironmentState;
  upgrade: EnvironmentUpgradeState;
  onClose: () => void;
}

/** 分组的出场顺序：frago 自己、必装、选装、agent 命令行。 */
const GROUP_ORDER: Array<EnvironmentItem['group']> = ['frago', 'required', 'optional', 'agent'];

/**
 * 一格的处境，也就是第一行那句结论。
 *
 * 五档，按「要不要人动手」排的：needs-you 升级没成、要人自己来；missing-required
 * 缺了必需的东西；outdated 有新版（点一下就升，不急）；missing 这项能力还没开；
 * ok 没事。只有前两档上色——全都标上颜色，等于哪一档都没被标出来。
 */
type Tone = 'needs-you' | 'missing-required' | 'outdated' | 'missing' | 'ok';

function toneOf(item: EnvironmentItem, job?: EnvironmentUpgradeItemState): Tone {
  if (job?.state === 'manual' || job?.state === 'failed') return 'needs-you';
  if (!item.installed) return item.required ? 'missing-required' : 'missing';
  return item.outdated ? 'outdated' : 'ok';
}

/**
 * 这一格能不能点升级。
 *
 * 落后的能升，没装的能装。frago 自己在本地构建的机器上不给按钮——那一格的两个数字
 * 比出来本来就是反的，按下去只会把本地构建覆盖成更旧的线上版。没有公开版本源的
 * （WorkBuddy）也不给：升到哪儿去都说不出来。
 */
function isUpgradable(item: EnvironmentItem, fragoSource: string): boolean {
  if (item.id === 'frago' && fragoSource === 'local') return false;
  if (!item.latest) return false;
  return item.outdated || !item.installed;
}

function formatCheckedAt(seconds: number | null): string {
  if (!seconds) return '';
  return new Date(seconds * 1000).toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * 那条要人自己去终端跑的命令，配一颗复制按钮。
 *
 * 命令只有能原样拿走才算交付。让人从一段说明里把命令挑出来手敲，是把最后一步的成本
 * 又推回给他，而那一步正是他找我们来解决的。
 */
function ManualCommand({ command }: { command: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // 剪贴板不给用（非安全来源、权限被拒）时命令仍然摆在屏上，人能自己选中复制。
    }
  };

  return (
    <div className="envc-manual">
      <code className="envc-manual-cmd">{command}</code>
      <button
        type="button"
        className="envc-manual-copy"
        onClick={() => void copy()}
        title={t('envCheck.copy')}
        aria-label={t('envCheck.copy')}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
      </button>
    </div>
  );
}

export default function EnvironmentModal({ environment, upgrade: job, onClose }: Props) {
  const { t } = useTranslation();
  const { data, loading, error, reload } = environment;
  const { status, upgrade, busy } = job;

  const items = data?.items ?? [];
  const fragoSource = data?.frago_source ?? 'unknown';
  const pending = items.filter((i) => isUpgradable(i, fragoSource));

  const groups = GROUP_ORDER.map((group) => ({
    group,
    rows: items.filter((i) => i.group === group),
  })).filter((g) => g.rows.length > 0);

  const stateOf = (id: string): EnvironmentUpgradeItemState | undefined => status?.items?.[id];

  /* 刚才那一下成了没有，摆在最上面。
     升级关了窗还在跑，人回头再打开时最想知道的就是这个——那句话不该藏在某一格里
     等人自己去找。只数两个数：升好了几样、还要人自己动手几样；「不用升」不占篇幅，
     它对人没有任何要求。 */
  const done = status && !status.running && status.order.length > 0;
  const tally = done
    ? status.order.reduce(
        (acc, id) => {
          const state = status.items[id]?.state;
          if (state === 'ok') acc.ok += 1;
          else if (state === 'manual' || state === 'failed') acc.needsYou += 1;
          return acc;
        },
        { ok: 0, needsYou: 0 }
      )
    : null;

  return (
    // 遮罩不接点击：这扇窗只认关闭按钮，理由见文件开头。
    <div className="envc-overlay">
      <div className="envc-card" role="dialog" aria-modal="true" aria-label={t('envCheck.title')}>
        <div className="envc-header">
          <div className="envc-title">
            {t('envCheck.title')}
            <span className="envc-subtitle">
              {data?.checked_at
                ? t('envCheck.checkedAt', { time: formatCheckedAt(data.checked_at) })
                : t('envCheck.neverChecked')}
            </span>
          </div>
          <div className="envc-header-actions">
            {pending.length > 0 ? (
              <button
                type="button"
                className="envc-upgrade-all"
                onClick={() => void upgrade(pending.map((i) => i.id))}
                disabled={busy}
              >
                {busy ? <Loader2 size={13} className="cs-spin" /> : <ArrowUp size={13} />}
                {busy
                  ? t('envCheck.upgradingAll')
                  : t('envCheck.upgradeAll', { n: pending.length })}
              </button>
            ) : null}
            <button
              type="button"
              className="envc-icon-btn"
              onClick={() => void reload(true)}
              disabled={loading || busy}
              title={t('envCheck.refresh')}
              aria-label={t('envCheck.refresh')}
            >
              <RefreshCw size={14} className={loading ? 'cs-spin' : ''} />
            </button>
            <button
              type="button"
              className="envc-icon-btn"
              onClick={onClose}
              title={t('envCheck.close')}
              aria-label={t('envCheck.close')}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {error ? <div className="envc-error">{error}</div> : null}

        {/* 升级是派 agent 去这台机器上真的装东西，不是界面里改个数字。说清楚它在干什么，
            人才知道为什么要等，以及等的时候机器上正在发生什么。 */}
        {busy ? <div className="envc-note envc-note--busy">{t('envCheck.busyNote')}</div> : null}

        {/* 跑完那一下的结果。要人动手的那几样底下各自摆着命令，这里只说还剩几样。 */}
        {tally ? (
          <div
            className={`envc-note ${tally.needsYou > 0 ? 'envc-note--failed' : 'envc-note--done'}`}
          >
            {tally.needsYou > 0
              ? t('envCheck.doneNeedsYou', { ok: tally.ok, n: tally.needsYou })
              : t('envCheck.doneAllGood', { ok: tally.ok })}
          </div>
        ) : null}

        {/* 开发机上的 frago 是自己构建装上去的，版本号通常比线上大。不说明这一句，
            那一格写着「本机 1.2.242 · 外面 1.2.0」会读成 frago 落后了。 */}
        {fragoSource === 'local' ? (
          <div className="envc-note">{t('envCheck.localBuildNote')}</div>
        ) : null}

        <div className="envc-body">
          {groups.length === 0 && !loading ? (
            <div className="envc-empty">{t('envCheck.empty')}</div>
          ) : null}

          {groups.map(({ group, rows }) => (
            <section key={group} className="envc-group">
              <h3 className="envc-group-title">{t(`envCheck.group.${group}`)}</h3>
              <div className="envc-grid">
                {rows.map((item) => {
                  const job = stateOf(item.id);
                  const tone = toneOf(item, job);
                  const upgradable = isUpgradable(item, fragoSource);
                  // 这一轮正在做这一格，那句结论就让位给进度——「有新版」这时候是废话。
                  const working = job?.state === 'running' || job?.state === 'pending';

                  return (
                    <div key={item.id} className={`envc-cell envc-cell--${tone}`}>
                      <div className="envc-cell-head">
                        <span className="envc-cell-name" title={item.name}>
                          {item.name}
                        </span>
                        {item.required ? (
                          <span className="envc-tag">{t('envCheck.tag.required')}</span>
                        ) : null}
                      </div>

                      {/* 第一行是结论。人打开这扇窗要知道的第一件事是「这一样要不要紧」，
                          不是它的版本号——版本号退到下一行。 */}
                      <div className={`envc-verdict envc-verdict--${tone}`}>
                        {working ? (
                          <>
                            <Loader2 size={12} className="cs-spin" />
                            {t(`envCheck.job.${job?.state}`)}
                          </>
                        ) : (
                          t(`envCheck.verdict.${tone}`)
                        )}
                      </div>

                      {/* 版本号退成小字：想核对的人看得到，不看也不妨碍读上面那句。 */}
                      <div className="envc-versions">
                        {/* 外面查不到版本的（只发桌面版那种），就别写「外面 —」——
                            一个破折号不是答案，说清楚查不到才是。 */}
                        {item.installed && item.latest
                          ? t('envCheck.versionLine', {
                              current: item.current ?? '—',
                              latest: item.latest,
                            })
                          : item.installed
                            ? t('envCheck.versionCurrentOnly', { current: item.current ?? '—' })
                            : item.latest
                              ? t('envCheck.versionLatestOnly', { latest: item.latest })
                              : t('envCheck.latestUnknown')}
                      </div>

                      {/* 升级没成的时候，把该由人做的那件事直接摆出来。 */}
                      {job?.state === 'manual' && job.message ? (
                        <ManualCommand command={job.message} />
                      ) : null}
                      {job?.state === 'failed' && job.message ? (
                        <div className="envc-cell-job envc-cell-job--failed">{job.message}</div>
                      ) : null}
                      {job?.state === 'ok' ? (
                        <div className="envc-cell-job envc-cell-job--ok">
                          <Check size={11} />
                          {job.message || t('envCheck.job.ok')}
                        </div>
                      ) : null}
                      {job?.state === 'skipped' && job.message ? (
                        <div className="envc-cell-job">{job.message}</div>
                      ) : null}

                      {upgradable && !working && job?.state !== 'ok' ? (
                        <button
                          type="button"
                          className="envc-cell-upgrade"
                          onClick={() => void upgrade([item.id])}
                          disabled={busy}
                        >
                          <ArrowUp size={12} />
                          {job ? t('envCheck.retryOne') : item.installed
                            ? t('envCheck.upgradeOne')
                            : t('envCheck.installOne')}
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
