// frontend/src/usePolicyPanel.ts
/**
 * State and actions of the policy panel (ADR 013): loads the live policy and, only for users who
 * may edit, the server draft; keeps the editable copy apart from the server draft; runs Save, Pin
 * and Reload one at a time; resets the "I reviewed this diff" tick whenever the draft changes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Translate } from "./findings";
import {
  fetchDraftPolicy,
  fetchLivePolicy,
  pinPolicy,
  PolicyError,
  reloadPolicy,
  saveDraftPolicy,
  type DraftPolicyResponse,
  type LivePolicyResponse,
} from "./policyApi";
import { isDraftChanged, policyErrorText } from "./policyErrors";
import { docsEqual, stableStringify, type PolicyDocument } from "./policyModel";

const EMPTY_POLICY: PolicyDocument = { version: 1, mode: "off", targets: {} };

/** Everything loaded from the server plus the editable copy. */
export interface PolicyData {
  live: LivePolicyResponse | null;
  /** The saved server draft (null: none exists, or the user may not read it). */
  draft: DraftPolicyResponse | null;
  /** The editable copy (null until the first successful load for an editor). */
  local: PolicyDocument | null;
  /** The document `local` was last reset to; `local` differs from it when there are unsaved edits. */
  base: PolicyDocument | null;
  loading: boolean;
}

const INITIAL: PolicyData = { live: null, draft: null, local: null, base: null, loading: true };

interface Loaded {
  live: LivePolicyResponse;
  draft: DraftPolicyResponse | null;
  draftError: unknown;
}

async function readDraft(): Promise<{ draft: DraftPolicyResponse | null; error: unknown }> {
  try {
    return { draft: await fetchDraftPolicy(), error: null };
  } catch (err) {
    if (err instanceof PolicyError && err.status === 404) return { draft: null, error: null };
    return { draft: null, error: err };
  }
}

/** Reads live (and, for editors, the draft); `alive` stops the second request once the load is stale. */
async function fetchAll(canEdit: boolean, alive: () => boolean): Promise<Loaded> {
  const live = await fetchLivePolicy();
  if (!canEdit || !alive()) return { live, draft: null, draftError: null };
  const { draft, error } = await readDraft();
  return { live, draft, draftError: error };
}

/** The data after a load: a failed draft read keeps what the editor already had. */
function mergeLoaded(prev: PolicyData, loaded: Loaded, canEdit: boolean): PolicyData {
  if (!canEdit) return { live: loaded.live, draft: null, local: null, base: null, loading: false };
  if (loaded.draftError) return { ...prev, live: loaded.live, loading: false };
  const doc = loaded.draft?.document ?? loaded.live.document ?? EMPTY_POLICY;
  return { live: loaded.live, draft: loaded.draft, local: doc, base: doc, loading: false };
}

interface Messages {
  setError: (e: string | null) => void;
  setNotice: (n: string | null) => void;
}

function useMounted() {
  const ref = useRef(true);
  useEffect(() => {
    ref.current = true;
    return () => { ref.current = false; };
  }, []);
  return ref;
}

function usePolicyLoader(enabled: boolean, canEdit: boolean, msg: Messages, t: Translate) {
  const [data, setData] = useState<PolicyData>(INITIAL);
  const [ticked, setTicked] = useState<string | null>(null);
  const mounted = useMounted();
  const seq = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;

  const load = useCallback(async () => {
    const mine = ++seq.current;
    try {
      const loaded = await fetchAll(canEdit, () => mounted.current && mine === seq.current);
      if (!mounted.current || mine !== seq.current) return;
      setData((prev) => mergeLoaded(prev, loaded, canEdit));
      setTicked(null);
      if (loaded.draftError) msg.setError(policyErrorText(loaded.draftError, tRef.current));
    } catch (err) {
      if (!mounted.current || mine !== seq.current) return;
      setData((prev) => ({ ...prev, loading: false }));
      msg.setError(policyErrorText(err, tRef.current));
    }
  }, [canEdit, mounted, msg]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  return { data, setData, ticked, setTicked, load, mounted };
}

/** Runs one action at a time; the ref blocks a second click before React re-renders. */
function useActionRunner(mounted: { current: boolean }, msg: Messages, t: Translate) {
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (job: () => Promise<void>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    msg.setError(null);
    msg.setNotice(null);
    try {
      await job();
    } catch (err) {
      if (mounted.current) msg.setError(policyErrorText(err, t));
    } finally {
      busyRef.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [mounted, msg, t]);
  return { busy, run };
}

export interface UsePolicyPanelArgs {
  /** False while the session is still being resolved: nothing is fetched yet. */
  enabled: boolean;
  canEdit: boolean;
  t: Translate;
}

type Loader = ReturnType<typeof usePolicyLoader>;
type Runner = ReturnType<typeof useActionRunner>["run"];

/** Save, Pin and Reload: each runs through `run`, so only one is in flight at a time. */
function usePolicyActions(loader: Loader, run: Runner, msg: Messages, t: Translate) {
  const { data, setData, setTicked, load } = loader;

  const save = useCallback(() => run(async () => {
    if (!data.local) return;
    const saved = await saveDraftPolicy(data.local);
    msg.setNotice(t("policy.actions.saveSuccess"));
    const fresh = await fetchDraftPolicy();
    const same = fresh.digest === saved.digest;
    setData((p) => ({ ...p, draft: fresh, base: fresh.document, local: same ? fresh.document : p.local }));
    setTicked(null);
  }), [run, data.local, msg, t, setData, setTicked]);

  const pin = useCallback(() => run(async () => {
    if (!data.draft) return;
    try {
      await pinPolicy(data.draft.digest);
    } catch (err) {
      if (!isDraftChanged(err)) throw err;
      await load();
      msg.setError(policyErrorText(err, t));
      return;
    }
    msg.setNotice(t("policy.actions.pinSuccess"));
    await load();
  }), [run, data.draft, load, msg, t]);

  const reload = useCallback(() => run(async () => {
    await reloadPolicy();
    msg.setNotice(t("policy.actions.reloadSuccess"));
    await load();
  }), [run, load, msg, t]);

  return { save, pin, reload };
}

export function usePolicyPanel({ enabled, canEdit, t }: UsePolicyPanelArgs) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const msg = useRef<Messages>({ setError, setNotice }).current;
  const loader = usePolicyLoader(enabled, canEdit, msg, t);
  const { busy, run } = useActionRunner(loader.mounted, msg, t);
  const { data, setData, ticked, setTicked } = loader;

  const reviewKey = data.draft ? `${data.draft.digest}|${stableStringify(data.draft.document)}` : null;
  const reviewed = reviewKey !== null && ticked === reviewKey;
  const dirty = data.local !== null && !docsEqual(data.local, data.base);
  const setLocal = useCallback((doc: PolicyDocument) => setData((p) => ({ ...p, local: doc })), [setData]);
  const discard = useCallback(() => setData((p) => ({ ...p, local: p.base })), [setData]);
  const setReviewed = useCallback((v: boolean) => setTicked(v ? reviewKey : null), [reviewKey, setTicked]);
  const actions = usePolicyActions(loader, run, msg, t);

  return { data, error, notice, busy, reviewed, dirty, setLocal, discard, setReviewed, ...actions };
}
