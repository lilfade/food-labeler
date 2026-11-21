# Cottage food state rules

Food Labeler's **Cottage food label** takes its required wording and its list
of required label items from a rules file. This page describes that file,
the user's own edits that sit on top of it, and how to update it.

> These are suggestions from public state guidance. Bakers are responsible
> for following their state's rules. Nothing here is legal advice.

## Three layers

| layer | file | who changes it |
|-------|------|----------------|
| 1. bundled rules | `food_labeler/cottage_rules.json` (inside the program) | replaced by every app update |
| 2. rules update | `<data folder>/cottage_rules.json` | *Settings → My bakery → Add state rules update file…* |
| 3. the baker's own edits | `<data folder>/cottage_overrides.json` | *Settings → My bakery* (wording, required items) |

The label uses layer 3 over layer 2 over layer 1. For each state, an imported
update (layer 2) is used only if its `checked_on` date is the same as or later
than the bundled entry's, so an old update file can never hide newer rules
that came with an app update. App updates never touch layer 3, nor the
baker's details (`my_bakery.json`), ingredients (`my_ingredients.json`) or
products (`my_products.json`). For the data folder's location, see
[ARCHITECTURE.md](ARCHITECTURE.md#settings-locations).

## Rules file format

UTF-8 JSON (a byte-order mark is fine):

```json
{
  "format": "food-labeler-cottage-rules",
  "version": 1,
  "updated": "2026-11-20",
  "states": [
    {
      "id": "NE",
      "name": "Nebraska",
      "sales_allowed": true,
      "verified": true,
      "statements": [
        {"id": "main", "text": "This food was prepared in a kitchen that is not subject to regulation and inspection by the regulatory authority and may contain allergens.", "min_pt": null, "kind": "label"}
      ],
      "required": ["business_name", "address"],
      "optional": ["product_name", "ingredients", "allergens"],
      "min_statement_pt": null,
      "metric_required": false,
      "notes": "Plain-English notes for the baker.",
      "source_url": "https://nebraskalegislature.gov/laws/statutes.php?statute=81-2,280",
      "extra_sources": ["https://nda.nebraska.gov/fscp/foods/cottagefood.html"],
      "checked_on": "2026-11-20"
    }
  ]
}
```

| key | meaning |
|-----|---------|
| `id` | two capital letters (`NE`, `DC`), or `custom` |
| `name` | shown in the state list |
| `sales_allowed` | `true`, `false` (home-baked goods can't be sold this way; the app warns) or `null` (not known) |
| `verified` | `true` only when the wording and items were checked against an official source (state agency, statute or administrative code). Otherwise the app shows "Unverified — check with your state". |
| `statements` | up to 8. `text` is copied **word for word** from the source. `min_pt` is the smallest type size in points the source allows (or `null`). `kind`: `label` (printed), `alternative` (other wording the state allows; the baker can switch to it), `optional` (needed only for some foods, e.g. foods kept cold; the baker can add it), `sign` (for a sign where you sell; shown, never printed). |
| `required`, `optional` | label items, from: `product_name`, `net_quantity`, `ingredients`, `allergens`, `business_name`, `address` (street, city, state and ZIP), `city_state_zip`, `phone`, `email`, `permit_number`, `date_made`, `sell_by`, `storage` |
| `min_statement_pt` | smallest size for every statement that has no `min_pt` of its own |
| `metric_required` | `true` adds grams/kilograms to the net weight (`Net Wt. 8 oz (227 g)`) |
| `notes`, `source_url`, `extra_sources`, `checked_on` | shown to the baker; `checked_on` is `YYYY-MM-DD` and also decides layering (above) |

A statement may contain the blanks `{business_name}`, `{permit_number}` and
`{county}`; they are filled from *My bakery*. Any other `{...}` is refused.

Whatever the file says, the app always asks for the product name,
ingredients, allergens, business name and the **complete** address (street,
city, state and ZIP), as High Thyme Kitchen's own labels do; a label never
shows half an address. The baker can change this list per state.

Validation is strict: one bad entry refuses the whole file, nothing is
written, and the app says why in plain words.

Points become printer dots as `ceil(pt × 203 / 72)`, used as the font's em
size: 10 pt = 29 dots, 12 pt = 34 dots. Statements are never drawn smaller;
if the label can't hold everything, printing is refused with a suggestion to
use a bigger label.

## The baker's own edits

`cottage_overrides.json`:

```json
{
  "format": "food-labeler-cottage-overrides",
  "version": 1,
  "states": {
    "NE": {
      "statements": {"main": {"text": "My wording", "based_on": "the state's wording when I edited it"}},
      "own": [{"id": "own1", "text": "A statement of my own", "min_pt": null}],
      "required": {"value": ["product_name", "ingredients"], "based_on": ["...the default list then..."]}
    }
  }
}
```

`based_on` remembers the default an edit was made against. When a later rules
file changes that default, the app asks once: *"Your state's suggested
wording was updated — keep yours or use the new one?"* Keeping yours updates
`based_on` (so it isn't asked again); using the new one deletes the edit. A
broken overrides file is renamed to `cottage_overrides.json.broken` and never
overwritten.

## Updating the rules

1. Check each changed state against its **official** source (state
   department of agriculture or health, statute, administrative code). Blog
   and advocacy summaries are only a way to find the official source.
2. Copy statement wording exactly, including capitals and punctuation.
   Never paraphrase or invent wording; if no exact wording is prescribed,
   leave `statements` empty and say so in `notes`.
3. Update `source_url` and set `checked_on` to the day you checked. If you
   can't confirm a state, set `verified` to `false` and start `notes` with
   "Unverified — check with your state."
4. Run the tests (`tests/test_cottage.py` validates the bundled file) and
   `tools/render_samples.py`, and look at `docs/samples/cottage-*.png`.
5. To send changes to bakers without a new program, give them a rules file
   containing just the changed states; they add it in *Settings → My bakery*,
   and the app lists what changed.

## States in the bundled file

Checked 2026-11-20. "Statement" shows the printed wording (other kinds are in
the file). This table is a summary; the file is what the app uses.

| state | verified | statement on the label | min size | source |
|-------|----------|------------------------|----------|--------|
| Alabama | yes | none prescribed (see notes) | 10 pt | [source](https://admincode.legislature.state.al.us/api/rule/420-3-22-.01) |
| Alaska | yes | “This food was made in a home kitchen, is not regulated or inspected, except for meat and meat products, and may contain allergens.” | — | [source](https://www.akleg.gov/pdf/33/Bills/HB0251C.pdf) |
| Arizona | yes | “This product was produced in a home kitchen that may come in contact with common food allergens and pet allergens and is not subject to public health inspection.” / “To obtain additional information about cottage foods or to report a food-borne illness, go to azdhs.gov/Cottagefood” | — | [source](https://www.azleg.gov/ars/36/00932.htm) |
| Arkansas | yes | “This product was produced in a private residence that is exempt from state licensing and inspection. This product may contain allergens.” | — | [source](https://healthy.arkansas.gov/wp-content/uploads/Homemade-Food-Guide-5.21.2026-Update.pdf) |
| California | yes | “Made in a Home Kitchen” | 12 pt | [source](https://www.icphd.org/assets/Environmental-Health/Food/Cottage-Food/CFLabelingReq.pdf) |
| Colorado | yes | “This product was produced in a home kitchen that is not subject to state licensure or inspection and that may also process common food allergens such as tree nuts, peanuts, eggs, soy, wheat, milk, fish, and crustacean shellfish. This product is not intended for resale.” | — | [source](https://colorado.public.law/statutes/crs_25-4-1614) |
| Connecticut | yes | “Made in a Cottage Food Operation that is not Subject to Routine Government Food Safety Inspection.” | 10 pt | [source](https://portal.ct.gov/dcp/knowledge-base/articles/cottage-foods/cottage-food-label-checklist) |
| Delaware | yes | “This food is made in a Cottage Food Establishment and is NOT subject to routine Government Food Safety Inspections” | 10 pt | [source](https://regulations.delaware.gov/api/register/february2026/f36c1f42-d73c-4700-9153-e1f04fdcfaec) |
| District of Columbia | yes | “Made by a cottage food business that is not subject to the District of Columbia's food safety regulations.” | 10 pt | [source](https://code.dccouncil.gov/us/dc/council/code/sections/7-742.02) |
| Florida | yes | “Made in a cottage food operation that is not subject to Florida’s food safety regulations.” | 10 pt | [source](http://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0500-0599/0500/Sections/0500.80.html) |
| Georgia | yes | “MADE IN A COTTAGE FOOD OPERATION THAT IS NOT SUBJECT TO STATE FOOD SAFETY INSPECTIONS.” | 10 pt | [source](https://www.law.cornell.edu/regulations/georgia/Ga-Comp-R-Regs-R-40-7-19-.09) |
| Hawaii | yes | “Made in a home kitchen not routinely inspected by the Department of Health” | — | [source](https://www.law.cornell.edu/regulations/hawaii/Haw-Code-R-SS-11-50-35) |
| Idaho | yes | “This product is not subject to government food safety inspection or licensing requirements. It may contain allergens.” | — | [source](https://legislature.idaho.gov/wp-content/uploads/sessioninfo/2026/legislation/S1283.pdf) |
| Illinois | yes | “This product was produced in a home kitchen not inspected by a health department that may also process common food allergens. If you have safety concerns, contact your local health department.” | — | [source](https://ilga.gov/legislation/ilcs/documents/041006250K4.htm) |
| Indiana | yes | “This product is home produced and processed, and the production area has not been inspected by the State Department of Health. NOT FOR RESALE.” | 10 pt | [source](https://secure.in.gov/health/food-protection/files/Indiana-Home-Based-Vendor-Handbook-2.pdf) |
| Iowa | yes | “This product was produced at a home food processing establishment.” | — | [source](https://www.legis.iowa.gov/docs/code/137D.html) |
| Kansas | yes | none prescribed (see notes) | — | [source](https://bookstore.ksre.ksu.edu/pubs/foods-sold-directly-to-consumers-in-kansas-regulations-and-food-safety-best-practices_MF3138.pdf) |
| Kentucky | yes | “This product is home-produced and processed” | 10 pt | [source](https://apps.legislature.ky.gov/law/statutes/statute.aspx?id=57382) |
| Louisiana | yes | none prescribed (see notes) | — | [source](https://www.legis.la.gov/Legis/LawPrint.aspx?d=98431) |
| Maine | yes | none prescribed (see notes) | — | [source](https://www.law.cornell.edu/regulations/maine/01-001-C-M-R-ch-345-SS-7) |
| Maryland | yes | “Made by a cottage food business that is not subject to Maryland’s food safety regulations.” | 10 pt | [source](https://mgaleg.maryland.gov/2026RS/Statute_Web/ghg/21-330.1.pdf) |
| Massachusetts | yes | none prescribed (see notes) | — | [source](https://southboroughma.gov/DocumentCenter/View/743/Retail-Food-Code-Standards-for-Permitted-Residential-Kitchens-PDF) |
| Michigan | yes | “Made in a home kitchen that has not been inspected by the Michigan department of agriculture and rural development.” | 11 pt | [source](https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-289-4102) |
| Minnesota | yes | “These products are homemade and not subject to state inspection.” | — | [source](https://www.revisor.mn.gov/statutes/cite/28A.152) |
| Mississippi | yes | “Made in a cottage food operation that is not subject to Mississippi's food safety regulations.” | 10 pt | [source](https://billstatus.ls.state.ms.us/documents/2026/html/HB/0900-0999/HB0910IN.htm) |
| Missouri | **unverified** | none prescribed (see notes) | — | [source](https://revisor.mo.gov/main/OneSection.aspx?section=196.298) |
| Montana | yes | “Made in a home kitchen that is not subject to retail food establishment regulations or inspections.” | 11 pt | [source](https://archive.legmt.gov/bills/mca/title_0500/chapter_0500/part_0010/section_0160/0500-0500-0010-0160.html) |
| Nebraska | yes | “This food was prepared in a kitchen that is not subject to regulation and inspection by the regulatory authority and may contain allergens.” | — | [source](https://nebraskalegislature.gov/laws/statutes.php?statute=81-2,280) |
| Nevada | yes | “MADE IN A COTTAGE FOOD OPERATION THAT IS NOT SUBJECT TO GOVERNMENT FOOD SAFETY INSPECTION” | — | [source](https://www.leg.state.nv.us/NRS/NRS-580.html) |
| New Hampshire | yes | “This product is exempt from New Hampshire licensing and inspection.” | 10 pt | [source](https://gc.nh.gov/rsa/html/X/143-A/143-A-12.htm) |
| New Jersey | yes | “This food is prepared pursuant to N.J.A.C. 8:24-11 in a home kitchen that has not been inspected by the Department of Health.” | — | [source](https://www.nj.gov/health/cottagefood/requirements/labeling) |
| New Mexico | yes | “This product is home produced and is exempt from state licensing and inspection. This product may contain allergens.” | — | [source](https://nmlegis.gov/Sessions/21%20Regular/final/HB0177.PDF) |
| New York | yes | “Made in a Home Kitchen” | 4.5 pt | [source](https://agriculture.ny.gov/food-safety/home-processing) |
| North Carolina | yes | none prescribed (see notes) | — | [source](https://www.ncagr.gov/divisions/food-drug-protection/food-program/fdpd-food-program-home-processor) |
| North Dakota | yes | “This product is made in a home kitchen that is not inspected by the state or local health department.” | — | [source](https://ndlegis.gov/cencode/t23c09-5.pdf) |
| Ohio | yes | “This product is home produced.” | 10 pt | [source](https://codes.ohio.gov/ohio-revised-code/section-3715.023) |
| Oklahoma | yes | “This product was produced in a facility that is exempt from government licensing and inspection.” | 10 pt | [source](https://www.oklegislature.gov/cf_pdf/2025-26%20ENR/hB/HB3720%20ENR.PDF) |
| Oregon | yes | “This product is homemade, is not prepared in an inspected food establishment, and must be stored and displayed separately if merchandised by a retailer.” | — | [source](https://www.oregon.gov/oda/Documents/Publications/FoodSafety/CottageFoodExemptionENG.pdf) |
| Pennsylvania | yes | none prescribed (see notes) | — | [source](https://www.pa.gov/content/dam/copapwp-pagov/en/pda/documents/consumer_protection/foodsafety/documents/limited%20food%20establishment%20application%20packet.pdf) |
| Rhode Island | yes | “Made by a Cottage Food Business Registrant that is not Subject to Routine Government Food Safety Inspection” | 10 pt | [source](http://webserver.rilegislature.gov/Statutes/TITLE21/21-27/21-27-6.2.htm) |
| South Carolina | yes | “PROCESSED AND PREPARED BY A HOME-BASED FOOD PRODUCTION OPERATION THAT IS NOT SUBJECT TO SOUTH CAROLINA'S FOOD SAFETY REGULATIONS.” | — | [source](https://www.scstatehouse.gov/code/t44c001.php) |
| South Dakota | yes | “This product was not produced in a commercial kitchen. It has been home-processed in a kitchen that may also process common food allergens such as tree nuts, peanuts, eggs, soy, wheat, milk, fish, and crustacean shellfish.” | — | [source](https://sdlegislature.gov/api/Statutes/34-18-37.html) |
| Tennessee | yes | “This product was produced at a private residence that is exempt from state licensing and inspection. This product may contain allergens.” | — | [source](https://foodscience.tennessee.edu/wp-content/uploads/sites/52/2025/12/TENN_53-1-118_FINAL.pdf) |
| Texas | yes | “THIS PRODUCT WAS PRODUCED IN A PRIVATE RESIDENCE THAT IS NOT SUBJECT TO GOVERNMENTAL LICENSING OR INSPECTION.” | — | [source](https://www.dshs.texas.gov/foodestablishments/cfpo) |
| Utah | yes | “Home Produced” | 12 pt | [source](https://www.law.cornell.edu/regulations/utah/Utah-Admin-Code-R70-560-6) |
| Vermont | yes | “Made in a home kitchen not inspected by the Vermont Department of Health” | 10 pt | [source](https://www.healthvermont.gov/node/386) |
| Virginia | yes | “NOT FOR RESALE PROCESSED AND PREPARED WITHOUT STATE INSPECTION.” | — | [source](https://law.lis.virginia.gov/vacode/title3.2/chapter51/section3.2-5130/) |
| Washington | yes | “Made in a home kitchen that has not been subject to standard inspection criteria.” | 11 pt | [source](https://app.leg.wa.gov/RCW/default.aspx?cite=69.22.020) |
| West Virginia | **unverified** | “This product was made in a non-commercial kitchen establishment that may not be subject to inspection and may contain cross-contact allergens not included in the allergen statement.” | — | [source](https://agriculture.wv.gov/wp-content/uploads/Farmers-Market-Vendor-Guide.pdf) |
| Wisconsin | yes | none prescribed (see notes) | — | [source](https://datcp.wi.gov/Documents2/HomemadeBakedGoods.pdf) |
| Wyoming | yes | none prescribed (see notes) | — | [source](https://wyoleg.gov/statutes/compress/title11.pdf) |
