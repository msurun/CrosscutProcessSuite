// Short notice shown after a view saved a change into the site draft (#247): nothing is live until
// the draft is published on Site > Versions (and approved where the catalogue rule requires it).
import type { ReactElement } from "react";

import type { Translate } from "../findings";

/** "Saved to the site draft, publish it on Site > Versions." */
export function DraftNotice({ t }: { t: Translate }): ReactElement {
  return (
    <p role="status" className="notice" data-testid="draft-notice">
      {t("draftNotice.saved")}
    </p>
  );
}
