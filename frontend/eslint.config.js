// Minimal ESLint flat config: size limits as WARNINGS (code standard: functions up to 40 lines,
// 4 parameters) on the files rewritten on 2026-10-20 only. Run: npm run lint.
import tseslint from "typescript-eslint";

const TOUCHED = [
  "src/App.tsx",
  "src/api.ts",
  "src/components/BacktestPanel.tsx",
  "src/components/BenefitPage.tsx",
  "src/components/ContextBar.tsx",
  "src/components/CurrentSettingsCompare.tsx",
  "src/components/ErrorBoundary.tsx",
  "src/components/FuzzyPage.tsx",
  "src/components/FuzzyState.ts",
  "src/components/FuzzySystemBar.tsx",
  "src/components/FuzzyTabs.tsx",
  "src/components/KnowledgeEditor.tsx",
  "src/components/KnowledgeFields.tsx",
  "src/components/LoopDetail.tsx",
  "src/components/LoopsOverview.tsx",
  "src/components/LoopsPage.tsx",
  "src/components/MembershipChart.tsx",
  "src/components/RulesEditor.tsx",
  "src/components/SettingsTables.tsx",
  "src/components/StatusChip.tsx",
  "src/components/Stepper.tsx",
  "src/components/TagList.tsx",
  "src/components/TrendPane.tsx",
  "src/components/TrendsPage.tsx",
  "src/components/TuningPage.tsx",
  "src/components/ValveChecklist.tsx",
  "src/components/ValvePlanView.tsx",
  "src/components/ValveRecordStep.tsx",
  "src/components/ValveResultView.tsx",
  "src/components/ValveSettingsForm.tsx",
  "src/components/ValveTestPage.tsx",
  "src/components/WindowPicker.tsx",
  "src/components/knowledgeDraft.ts",
  "src/findings.ts",
  "src/format.ts",
  "src/route.ts",
  "src/tagGroups.ts",
  "src/trendData.ts",
  "src/useRoute.ts",
  "src/valveTest.ts",
  "src/worklist.ts",
];

// The code carries `eslint-disable react-hooks/...` comments; this stub makes the rule name known
// without installing the plugin.
const hooksStub = { rules: { "exhaustive-deps": { meta: {}, create: () => ({}) } } };

export default tseslint.config({
  files: TOUCHED,
  plugins: { "react-hooks": hooksStub },
  languageOptions: { parser: tseslint.parser },
  rules: {
    "max-lines-per-function": ["warn", { max: 40, skipBlankLines: true, skipComments: true }],
    "max-params": ["warn", 4],
  },
});
