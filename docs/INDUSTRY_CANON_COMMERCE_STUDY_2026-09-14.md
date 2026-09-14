# Research canon — commerce, consumer & services industries

*For Aughor industry packages. Compiled 2026-09-14. Web research only.*

**Scope.** Fourteen new industries in depth (§1–§14), a gap check for the six existing packages (§15), and a cross-industry note (§16). §17 lists the claims I could not verify in this pass.

**Conventions used throughout**

- **Sources.** Every benchmark carries a bracketed source number, listed at the end of its section. Several labels mark how a figure was obtained:
  - **(computed)**: arithmetic on cited figures, not a published number.
  - **(aggregator)**: taken from a secondary compiler rather than the primary study.
  - **(as summarised)**: the page blocked automated fetching, so the figure comes from its search-index summary.
- **Benchmarks are dated measurements, not constants.** Each has a date and population, and a note on what drives it. Where no public benchmark could be verified, the table says so; no number was invented.
- **Grain** means what one row or unit of measure is. The rule everywhere: sum numerators and denominators at the stated grain, then divide.
- **Standards are a quarry for names.** Nothing here proposes adopting a reference model wholesale.
- **Licence shorthand.** NC = non-commercial. BY = attribution. OGL = UK Open Government Licence.

---

## 1. Hotels & lodging (incl. short-term rental)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Occupancy** (Occ %, OCC) | Rooms sold ÷ rooms available [1] | Property × stay-night. Roll up by summing sold and available. | US FY2025: 62.3%, down 1.2% YoY. NYC: 84.1% [2] | Averaging occupancy across hotels or days. Using booking date instead of stay date. Silently changing supply (out-of-order rooms, renovations). Undeclared treatment of complimentary and house-use rooms. |
| **ADR** (average daily rate, average room rate) | Rooms revenue ÷ rooms sold [1] | Property × stay-night | US FY2025: $160.54, up 0.9%. NYC: $333.71 [2] | Mixing tax-inclusive and exclusive rates, or packages (breakfast, resort fees). Averaging ADRs. Mixing currencies before conversion. |
| **RevPAR** | Rooms revenue ÷ rooms available = Occ × ADR [1] | Property × stay-night | US FY2025: $100.02, down 0.3%. NYC: $280.71 [2] | Multiplying an averaged occupancy by an averaged ADR across hotels. Reading "RevPAR up" without the occupancy/ADR split. |
| **RevPAR Index (RGI) · Occupancy Index (MPI) · ADR Index (ARI)** | Hotel metric ÷ competitive-set metric × 100. 100 = fair share [1] | Property × period vs comp set | 100 is fair share by construction | Comparing indices across different comp sets. A comp-set change breaks the time series. Ignoring index and reading market-wide growth as performance. |
| **TRevPAR · GOPPAR** | Total revenue (all departments) ÷ rooms available. Gross operating profit ÷ rooms available (USALI-style departmental P&L [13]) | Property × month | No free public benchmark verified. Varies strongly by service level: full-service with F&B vs select-service | Dividing by *occupied* rooms (a different metric, "per occupied room"). Mixing USALI editions or undistributed-expense allocations. |
| **Cancellation rate · no-show rate** | Cancelled ÷ bookings created, per booking-date cohort. No-shows ÷ arrivals due | Reservation | D-EDGE, 2023 Europe: direct 18%, Expedia 31%, Booking Holdings 42%. 2023 Asia: Booking Holdings 40%, Expedia 24% [4]. APAC 2026 report: direct 9.2%; Booking.com cancelled bookings made 68.6 days out vs 27.1 for kept ones (as summarised) [5] | Measuring on cancellation date instead of creation cohort. Not right-censoring recent cohorts (they have not had time to cancel). Mixing gross and net bookings. |
| **Lead time · length of stay (LOS)** | Arrival date − booking date. Nights per stay | Reservation | Dataset-derived; no universal benchmark | Averaging lead time including cancellations, which skew long [5]. Averaging LOS over bookings when the question is room-nights. |
| **Channel mix · acquisition cost · net RevPAR** ("revenue capture") | Share of room-nights or revenue by channel. Acquisition cost (commissions, CRS/GDS fees, loyalty, marketing) ÷ guest-paid revenue. Net revenue = guest-paid revenue − acquisition cost | Reservation × channel | Kalibri Labs: acquisition cost averages 15–25% of guest-paid revenue, some hotels up to 35%; about 20% for US hotels [6] | Optimising RevPAR while net RevPAR falls. Comparing OTA and direct ADR as if margins were equal. |
| **STR occupancy · nights booked** | Booked nights ÷ available nights. A calendar "unavailable" night is **not** a booked night [7] | Listing × night | Inside Airbnb *models* occupancy: 50% review rate, 3-night default stay, 70% cap [7] | Treating blocked nights as booked. Counting listings instead of active, bookable listings. Mixing entire homes with private rooms. |
| **GBV · take rate** (STR platforms) | GBV = booking value incl. host earnings, service fees, cleaning fees and taxes, net of cancellations and alterations. Take rate = revenue ÷ GBV [8] | Booking | Airbnb FY2024: GBV $81.8B, 491.5M Nights & Experiences Booked, revenue $11.1B. Revenue ≈ 13.6% of GBV; GBV per night & seat ≈ $166 (computed) [9] | GBV is counted at booking, revenue at check-in, so the ratio has timing noise [8]. GBV per night includes taxes and cleaning, so it is not the host's ADR. |

### Playbook

1. **RevPAR falls.** Split into occupancy vs ADR, then check in order:
   1. RGI/MPI/ARI against the comp set — is this a market problem or a share problem?
   2. Segment mix: transient, group, contract.
   3. Channel mix and rate parity.
   4. Supply changes: new rooms, out-of-order rooms.
   5. Calendar shifts (holidays, events). Compare day-of-week aligned.
   6. Pickup pace on future stay dates.

   *Operator action:* adjust rates and restrictions (min LOS, closed-to-arrival), run a group displacement analysis, buy OTA visibility or promotions, redirect sales effort.
2. **Occupancy rises but net RevPAR or GOPPAR falls.** Check in order:
   1. Shift toward commissionable channels.
   2. Discounted rate plans and packages.
   3. Acquisition cost per booking [6].
   4. Labour cost per occupied room.

   *Action:* push direct and member rates, renegotiate commissions, close discounted channels on peak nights.
3. **Cancellation rate rises.** Cut the rate by:
   1. Channel (free-cancellation OTA share) [4].
   2. Lead-time bucket [5].
   3. Refundable vs non-refundable rate plan.
   4. Source market.
   5. Group wash (blocked rooms released unsold).

   *Action:* recalibrate overbooking, add non-refundable rate fences, tighten deposit policy.
4. **ADR falls with flat occupancy.** Check in order:
   1. Room-type mix and upsell take-up.
   2. Rate-plan mix.
   3. LOS discounts.
   4. FX.
   5. Comp-set price moves.

   *Action:* re-price, run upsell at booking or check-in.
5. **STR listing revenue falls.** Check in order:
   1. Host-blocked days.
   2. Minimum-nights and regulatory limits [7].
   3. Price vs local comparables.
   4. Review count and score.
   5. Instant-book availability.

   *Action:* dynamic pricing, calendar hygiene, compliance fixes.

### Ontology sketch

**Objects (18).** Property · Room Type · Room · Rate Plan · Inventory (room type × stay date) · Reservation · Room-Night (Stay) · Guest Profile · Account (company or travel agent) · Group Block · Channel · Folio · Payment · Housekeeping Task · Maintenance Work Order · Review · Competitive Set · STR Listing / Host / Calendar-Day.

**Links**
- Property 1:N Room Type 1:N Room.
- Reservation N:1 Guest (booker). Reservation N:M Guest (occupants).
- Reservation N:1 Rate Plan. Reservation N:1 Channel.
- Reservation 1:N Room-Night. Room-Night N:1 Room — assigned at check-in, and can change (room move).
- Reservation N:0..1 Group Block. Group Block N:1 Account.
- Reservation 1:N Folio (split folios). Folio 1:N Payment.
- Review N:1 Reservation. Property N:M Competitive Set.
- Listing N:1 Host. Calendar-Day N:1 Listing.

**Lifecycles**
- *Reservation:* tentative → confirmed (guaranteed / non-guaranteed) → [modified]* → checked-in → **checked-out** ∎. Other terminal states: **cancelled** ∎, **no-show** ∎. The public dataset encodes exactly Check-Out / Canceled / No-Show [14].
- *Room status:* occupied → vacant-dirty → vacant-clean → inspected/ready. Out-of-order and out-of-service are side states; declare whether each is removed from supply.
- *Group block:* prospect → tentative → definite → cut-off → **actualised** ∎. Or **lost / cancelled** ∎.
- *Folio:* open → settled → **closed** ∎. Direct-bill balances transfer to accounts receivable.
- *STR booking:* request or instant-book → accepted → checked-in → completed → **reviewed** ∎. Or **cancelled by guest / host** ∎.

**Processes & promises**
- Confirmation at booking.
- Room ready by the published check-in time.
- Cancellation deadline set by the rate plan.
- Rate parity across channels (contractual).
- Group cut-off date (block release).
- OTA commission invoicing (agency model) or payout (merchant model).
- Review response.

### Systems & standards

- **Systems:**
  - PMS: Oracle OPERA Cloud, Mews, Cloudbeds.
  - CRS: Sabre SynXis, Amadeus.
  - Channel managers: SiteMinder, D-EDGE.
  - RMS: IDeaS, Duetto.
  - GDS: Amadeus, Sabre, Travelport.
  - Benchmarking: STR/CoStar.
  - Acquisition-cost analytics: Kalibri.
  - STR operations: Guesty, Hostaway.
  - Market data: AirDNA.
  - Plus F&B POS, loyalty and CRM.
- **Standards (name quarry):**
  - **STR/CoStar glossary** for the occupancy/ADR/RevPAR/index vocabulary [1].
  - **OpenTravel** OTA 1.0 XML suite (releases 2001A–2024A) and the OpenTravel 2.0 object model, which covers availability, rates, reservations and profiles [10].
  - **HTNG**: joint work with OpenTravel since 2019, including a customer-profile spec; with HEDNA, the Open Payments Alliance [11][12].
  - **USALI** (Uniform System of Accounts for the Lodging Industry) for departmental P&L names [13].

### Validation datasets

1. **Hotel booking demand** (Antonio, Almeida & Nunes, *Data in Brief* 2019) [14].
   - Licence and size: CC BY 4.0. 119,390 bookings (city hotel 79,330, resort 40,060), arrivals Jul 2015–Aug 2017, 31 variables.
   - Fields include is_canceled, reservation_status, lead_time, adr, distribution_channel, market_segment, deposit_type, and reserved vs assigned room type.
   - *Computes:* cancellation and no-show rate by channel, segment, deposit type and lead time; ADR; room-nights on the books by stay date; LOS; repeat-guest share; room-type up/downgrades.
   - *Cannot compute:* occupancy or RevPAR (no rooms-available figure), comp-set indices, costs.
2. **Inside Airbnb** [7].
   - Licence and content: CC BY 4.0. Per-city listings, a 365-day forward calendar, reviews.
   - *Computes:* supply and host concentration, price distribution, *modelled* occupancy, review velocity.
   - *Caveat:* the calendar cannot separate booked from blocked nights.
3. **trivago RecSys Challenge 2019** [15].
   - Licence and size: non-commercial R&D licence, registration required. About 1.2M sessions, 19.7M actions, 927k accommodations.
   - *Computes:* the demand-side distribution funnel — search → impression → click-out — plus position bias and filter use.

### What generic analytics gets wrong here

- It averages ADR, occupancy and RevPAR across hotels or days instead of summing revenue, rooms sold and rooms available.
- It confuses booking date with stay date. Pace and pickup need both, deliberately.
- It reads RevPAR growth without the comp-set index, so a rising market looks like good management.
- It treats gross bookings as demand. It ignores cancellations and no-shows, and it does not right-censor recent booking cohorts.
- It celebrates top-line RevPAR while acquisition cost grows faster; net RevPAR and GOPPAR are the profit view [6].

### Sources

- [1] CoStar STR Benchmark glossary: https://www.costar.com/products/str-benchmark/resources/glossary (blocked to fetch; definitions as indexed)
- [2] Hotel Management, CoStar FY2025 US results: https://www.hotelmanagement.net/data-trends/costar-us-hotel-occupancy-revpar-down-yoy-2025 · Hotel Dive: https://www.hoteldive.com/news/hotel-occupancy-revpar-decline-2025/810212/
- [3] *(reserved)*
- [4] D-EDGE Hotel Distribution Report 2024: https://www.d-edge.com/wp-content/uploads/2024/04/Hotel-Distribution-Report-2024-EN.pdf · PhocusWire summary: https://www.phocuswire.com/Hotel-distribution-market-share-distribution-analysis · Hotel Management summary: https://www.hotelmanagement.net/tech/study-cancelation-rate-at-40-as-otas-push-free-change-policy
- [5] D-EDGE 2026 report (EMEA/APAC): https://www.d-edge.com/2026-hotel-distribution-report-emea-apac/ · WiT summary: https://www.webintravel.com/apac-hotel-distribution-sees-slower-growth-rising-regional-otas-and-direct-channels-under-pressure/
- [6] Hotel Management, Kalibri Labs CEO on acquisition cost: https://www.hotelmanagement.net/operate/consumer-acquisition-costs-too-high-and-growing-says-kalibri-labs-ceo · Kalibri, "Hotel Asset Valuation in the Digital Age": https://www.kalibrilabs.com/published-articles/hotel-asset-valuation-in-the-digital-age
- [7] Inside Airbnb data assumptions: https://insideairbnb.com/data-assumptions/ · Get the data: https://insideairbnb.com/get-the-data/
- [8] Airbnb 10-K FY2023 (definitions of GBV and Nights & Experiences Booked): https://www.sec.gov/Archives/edgar/data/1559720/000155972024000006/abnb-20231231.htm
- [9] CNBC, Airbnb Q4 & FY2024: https://www.cnbc.com/2025/02/13/airbnb-abnb-q4-earnings-2024.html · PhocusWire: https://www.phocuswire.com/airbnb-earnings-q4-2024
- [10] OpenTravel: https://opentravel.org/news/recommendations-released-for-future-of-hotel-distribution-connectivity-standards/ · API Evangelist profile (OTA 1.0 releases, OTM 2.0): https://github.com/api-evangelist/opentravel-alliance
- [11] AltexSoft, HTNG/OpenTravel/HEDNA specifications: https://www.altexsoft.com/blog/hotel-tech-specifications-htng-opentravel/
- [12] Hospitality Net, Open Payments Alliance: https://www.hospitalitynet.org/news/4098877/htng-in-partnership-with-hedna-and-opentravel-releases-an-open-payments-alliance-standards-specification-payment-recipients
- [13] HFTP USALI: https://www.hftp.org/usali/ (blocked to automated fetch — verify edition before citing in product)
- [14] Hotel booking demand datasets: https://www.sciencedirect.com/science/article/pii/S2352340918315191 · https://pmc.ncbi.nlm.nih.gov/articles/PMC6297060/
- [15] trivago RecSys 2019 data: https://recsys2019data.trivago.com/ · problem definition: https://github.com/recsyschallenge/2019/blob/master/docs/problem_definition.md

---

## 2. Online travel & travel marketplaces (OTA, metasearch, alternative accommodation)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Gross bookings** (GBV, TTV, GMV) | Total retail value of transactions booked, at booking time, incl. taxes and fees, reduced for cancellations and refunds (Expedia) [2]. Split agency vs merchant (Booking) [1] | Booking item, at booking date | Booking Holdings FY2024: $165.6B (merchant $104.2B, agency $61.4B) [3]. Expedia FY2024: $110.9B [2] | Comparing booking-date GB with stay-date revenue. Mixing gross and net of cancellations. FX translation effects. |
| **Room nights** (booked room nights) | Rooms × nights booked. Expedia includes hotel and property nights [2] | Booking item × night | Booking Holdings 2024: 1,144M, up 9.1% (also 83M rental-car days, 49M airline tickets) [1][3]. Expedia: up 9% [2] | Booked ≠ stayed. Later cancellations reverse the count. |
| **Revenue margin · take rate** | Revenue ÷ gross bookings [2] | Period | Expedia 2024: 12.3% [2]. Booking ≈ 14.3% ($23.7B ÷ $165.6B, computed) [1][3]. Airbnb ≈ 13.6% (computed; see §1) | Booking-date GB against revenue recognised at stay or travel. Mix of merchant (gross payments) vs agency (commission) models. Incentives and loyalty booked as contra-revenue. |
| **Merchant share** | Merchant GB ÷ total GB | Period | Booking ≈ 63% (104.2 ÷ 165.6, computed) [3] | Revenue margin moves mechanically with this mix; do not read it as pricing power. |
| **Look-to-book · search-to-book conversion** | Shopping requests ÷ bookings (the inverse of conversion) [4] | Session or API request | No universal benchmark. Airline and GDS contracts price excess look-to-book [4][5] | Bot or API shopping in the denominator. Treating metasearch click-outs as bookings. |
| **Position CTR · funnel conversion** | Clicks ÷ impressions by rank position. Bookings ÷ sessions | Impression / session | Dataset-derived [6][7] | Ignoring position bias. Evaluating ranking changes without the impression list. |
| **Cancellation rate** | Cancelled ÷ created, per booking cohort | Booking item | Channel-dependent; see §1 D-EDGE figures | Netting cancellations into the wrong period. |
| **Supply: bookable properties / listings** | Properties bookable in the period | Property | Booking.com 2024: ~4.0M properties, of which ~3.5M alternative accommodations and ~500k hotels [1] | Counting listed rather than bookable. Duplicates across brands. |
| **Marketing efficiency** | Performance marketing spend ÷ gross bookings (or ÷ revenue). Direct/app share of bookings | Period × channel | No verified public benchmark — trend your own | Last-click paid attribution of repeat direct customers. |

### Playbook

1. **Gross bookings fall.** Decompose into room nights × average booking value × (1 − cancellation rate). Then check in order:
   1. Traffic by channel: SEO, SEM, metasearch, app, direct.
   2. Conversion by device and market.
   3. Price competitiveness and availability (parity breaks, sold-outs).
   4. Mix: geography, lead time, trip type.
   5. FX.

   *Action:* change metasearch and SEM bids, run supplier promotions, add loyalty incentives.
2. **Take rate falls.** Check in order:
   1. Merchant/agency mix.
   2. Coupons and loyalty incentives.
   3. Supplier commission tiers (preferred programmes).
   4. Payment cost and FX.
   5. B2B vs B2C mix.

   *Action:* renegotiate tiers, cut incentives, steer mix.
3. **Conversion falls.** Check in order:
   1. Rate parity violations or sold-out inventory.
   2. Release, latency or checkout errors.
   3. Traffic quality (bots inflate look-to-book).
   4. Ranking or sort changes.

   *Action:* roll back the release, correct rates, add bot filters.
4. **Cancellations rise.** Check in order:
   1. Lead-time distribution shift.
   2. Free-cancellation share.
   3. Specific suppliers or markets.
   4. Fraud rings.

   *Action:* rate fences, prepay incentives, fraud rules.
5. **Marketing cost per booking rises.** Check in order:
   1. CPC inflation on search and metasearch.
   2. Falling app/direct share.
   3. Falling repeat rate.

   *Action:* push the app and loyalty, change bid strategy.

### Ontology sketch

**Objects (16).** Traveler/Account · Search Session · Search Query · Impression · Offer · Booking/Itinerary (order) · Booking Item (stay / flight segment / car rental / activity) · Supplier/Partner · Property · Rate & Availability · Payment (merchant) · Commission Invoice (agency) · Change/Cancellation · Refund · Review · Marketing Channel / Campaign · Loyalty Account.

**Links**
- Traveler 1:N Search Session 1:N Query 1:N Impression N:1 Property.
- Traveler 1:N Booking 1:N Booking Item.
- Booking Item N:1 Supplier. Booking Item N:1 Offer.
- Booking 1:N Payment (merchant model). Booking Item N:1 Commission Invoice (agency model).
- Review N:1 Booking Item.
- Booking N:1 Marketing Channel (attribution — model-dependent, keep it versioned).

**Lifecycles**
- *Booking Item:* on-request → confirmed → [changed]* → travelled/checked-in → **completed** ∎. Or **cancelled** (free / penalty) ∎, **no-show** ∎.
- *Commission:* accrued → invoiced → **collected** ∎. Or **disputed** (no-show / cancellation claims) → adjusted ∎.
- *Session:* search → details → click-out or checkout → **booked** ∎. Or **abandoned** ∎.

**Processes & promises**
- Instant confirmation vs on-request (supplier SLA).
- Free-cancellation deadline.
- Price-match or parity guarantees.
- Refund timelines.
- Supplier payout (merchant model) or commission collection (agency model).
- Customer-service case resolution.

### Systems & standards

- **Systems:**
  - OTA and metasearch platforms.
  - Supplier connectivity via channel managers and CRS.
  - GDS: Amadeus, Sabre, Travelport.
  - Airline NDC/ONE Order APIs.
  - Payment processors.
  - Metasearch: Google Hotel Ads, trivago, Kayak.
- **Standards:**
  - **OpenTravel** message and object vocabulary [§1-10].
  - **HTNG** [§1-11].
  - **IATA ONE Order**, which replaces PNR, e-ticket and EMD with a single Order record and works alongside NDC [8].
  - Supplier definitions of *gross bookings* and *room nights* from 10-Ks [1][2].

### Validation datasets

1. **Personalize Expedia Hotel Searches (ICDM 2013)** [6].
   - Licence and size: Kaggle competition data (research use under competition rules; check before redistribution). About 399k search lists / 9.9M rows in train.
   - Fields: click and booking labels, rank position, price, promotion flag, competitor-OTA rate and availability fields.
   - *Computes:* position CTR and conversion, price competitiveness vs competitor OTAs, the parity effect on booking.
2. **trivago RecSys 2019** [7]. Session logs; non-commercial.
   - *Computes:* click-out rate by position, impression price vs click, filter use.
3. **Hotel booking demand** (§1). distribution_channel and market_segment fields.
   - *Computes:* channel mix and cancellation rate by channel (TA/TO vs direct vs GDS).

### What generic analytics gets wrong here

- It divides stay-date revenue by booking-date gross bookings within one period, so take-rate swings are timing artefacts.
- It reads a take-rate change as pricing power when merchant/agency mix or incentives changed.
- It lets bot and API shopping into conversion denominators, and counts metasearch click-outs as bookings.
- It evaluates search ranking without position bias, although the public datasets carry position fields.
- It books cancellations in the wrong period. Expedia reduces gross bookings for cancellations, so late cancellations of old bookings hit the current period.

### Sources

- [1] Booking Holdings 10-K FY2024: https://www.sec.gov/Archives/edgar/data/1075531/000107553125000010/bkng-20241231.htm
- [2] Expedia Group 10-K FY2024: https://www.sec.gov/Archives/edgar/data/1324424/000132442425000008/expe-20241231.htm · Q4 2024 release: https://s202.q4cdn.com/757635260/files/doc_financials/2024/q4/Earnings-Release-Q4-2024-vF.pdf
- [3] Booking Holdings Q4 2024 release: https://s201.q4cdn.com/865305287/files/doc_financials/2024/q4/Q4-2024-BKNG-Earnings-Release.pdf
- [4] PROS, look-to-book: https://pros.com/learn/blog/rethinking-the-look-to-book-ratio-how-direct-distribution-changes-the-economics-of-airline-retailing/
- [5] World Aviation Festival, look-to-book: https://worldaviationfestival.com/blog/airlines/look-to-book-the-old-new-evil/
- [6] Kaggle ICDM 2013: https://www.kaggle.com/c/expedia-personalized-sort/data · arXiv 1311.7679: https://arxiv.org/pdf/1311.7679
- [7] trivago RecSys 2019: https://recsys2019data.trivago.com/
- [8] IATA ONE Order: https://www.iata.org/en/programs/airline-distribution/retailing/one-order/

---

## 3. CPG / consumer brands (sell-in vs sell-through, trade promotion, retail media)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **%ACV distribution** (weighted distribution) | ACV (all-commodity volume: total store dollar sales) of stores carrying the item ÷ ACV of all stores in the market [1][2] | Item × market × week | 0–100 by construction | Averaging %ACV across items. Confusing *authorised* with *scanning* (actually selling). Mixing numeric distribution (store count) with weighted distribution. |
| **TDP** (total distribution points) | Sum of %ACV across the items of a brand or segment [2][3] | Brand × market × period | 5 SKUs at 50% ACV = 250 TDP [3] | SKU proliferation inflates TDP. Reading TDP growth as sales growth without velocity. |
| **Velocity** ($/TDP, $/MM ACV, SPPD) | Sales ÷ TDP, or ÷ $MM ACV of the stores selling [1] | Item/brand × market × week | Only meaningful within a category | Using $ per store, which ignores store size. Comparing velocity across very different distribution breadth (thin distribution often sits in the best stores). |
| **Base vs incremental volume · promo lift** | Incremental = actual − modelled baseline. Lift = incremental ÷ base. Split by tactic: TPR (temporary price reduction), feature, display. A TPR running 7+ weeks becomes the new base [4] | Item × store/market × week | Model-dependent | Baseline contaminated by post-promo dips and pantry loading. Ignoring cannibalisation and halo. |
| **Trade efficiency · promo ROI** | Incremental $ ÷ trade $ spent. >$1 = break-even [4][5] | Promotion event | Nielsen: almost ¾ of promotions don't break even (1M+ UPCs, 39M events, $555B sales). Discounts deeper than 25% degrade ROI [6] | ROI computed on retail sales instead of manufacturer margin. Ignoring forward buying by the retailer. |
| **Trade spend rate** (gross-to-net) | Trade $ (off-invoice, scan-backs, slotting, co-op/MDF, deductions) ÷ gross sales | Account × period | 15–25% of gross revenue. Primary figures cited: POI 2022 20–27%+; Cadent 2024 19.5% incl. marketing (aggregator) [7] | Deductions post months late, so net sales by account are unstable until true-up. Accrual vs cash mixing. |
| **Sell-in vs sell-through · channel weeks of supply** | Sell-in = manufacturer shipments (ERP). Sell-through = retailer POS units. WoS = (retailer on-hand + in-transit) ÷ average weekly POS | SKU × account × week | No public benchmark; targets are account-specific | Treating shipments as consumer demand (loading before a price rise or quarter end). Double counting distributor → retailer flows. |
| **On-shelf availability · OOS rate** | Share of SKU-store-days the item is not available to the shopper | SKU × store × day | 8.3% worldwide average (GMA/FMI/CIES, 2002) [8] | Inferring OOS from zero sales alone, which flags slow movers. Phantom inventory. |
| **Retail media ROAS vs incremental ROAS** | Attributed sales ÷ spend, vs incremental sales (control group or model) ÷ spend | Campaign × retailer | IAB/MRC (Jan 2024): outcome attribution on *viewable* impressions; incrementality via control groups or modelling [9] | Counting closed-loop attributed sales as incremental. Attribution windows that differ by network. Existing buyers targeted, so base sales get credited. |
| **Value/volume share · price index** | Brand ÷ category sales in the same syndicated universe. Price per equivalised unit ÷ category average | Brand × market × period | — | Mixing universes (e.g. all-outlet vs food channel). Unit equivalisation errors. |

### Playbook

1. **Consumer (POS) sales fall.** Split into distribution (TDP) × velocity × price, then check in order:
   1. TDP loss: delistings, OOS.
   2. Velocity by retailer and region.
   3. Price gaps vs competitors and private label.
   4. Lapping last year's big promotion.
   5. Competitor launches.
   6. Media and retail-media changes.

   *Action:* distribution recovery with key accounts, price-pack architecture, promo re-plan.
2. **Shipments (sell-in) rise while POS is flat.** Check in order:
   1. Channel weeks of supply.
   2. Forward buying before a list-price increase.
   3. Quarter-end loading.
   4. Pipeline fill for new distribution.

   *Action:* smooth shipments, adjust forecast. Expect a later dip, and possibly returns and markdowns.
3. **Promo ROI falls.** Check in order:
   1. Discount depth (>25%) [6].
   2. Frequency (diminishing returns) [6].
   3. Feature/display execution at store.
   4. Cannibalisation of sister SKUs.
   5. Forward buying.

   *Action:* cut depth and frequency, audit compliance, move funds to better tactics [4].
4. **Trade spend rate rises.** Check in order:
   1. Unplanned or invalid deductions.
   2. Slotting fees.
   3. Scan-back volume above plan.
   4. Accrual true-ups.

   *Action:* deduction-management clean-up, dispute invalid claims, renegotiate terms.
5. **OOS rises.** Check in order:
   1. Store ordering.
   2. DC-to-store fill.
   3. Supplier case fill.
   4. Promo forecast error.
   5. Phantom inventory.

   *Action:* order-parameter fixes, promo pre-builds, store audits.
6. **Retail-media ROAS rises but share is flat.** Check in order:
   1. Attribution window.
   2. Audience overlap with existing buyers.
   3. Viewability of impressions [9].

   *Action:* holdout or incrementality tests before scaling spend.

### Ontology sketch

**Objects (19).** Brand · Product/SKU (GTIN) · Pack hierarchy (each → case → pallet, one GTIN per level) · Retail Account (banner/chain) · Distributor · Store (GLN) · Sold-to/Ship-to · Customer Order · Order Line · Shipment (ASN) · Invoice · Deduction/Claim · Trade Promotion · Promotion Tactic · Trade Fund/Budget · POS Sales Record · Distribution/Planogram Record · Retail Media Campaign · Syndicated Market.

**Links**
- Brand 1:N Product 1:N Pack level.
- Retail Account 1:N Store.
- Order N:1 Account. Order 1:N Order Line N:1 Product.
- Order 1:N Shipment (partial shipments). Shipment 1:N Invoice line.
- Invoice 1:N Deduction. Deduction N:0..1 Promotion — the match is the hard part.
- Promotion N:1 Account. Promotion N:M Product. Promotion 1:N Tactic.
- POS Record N:1 Product × Store (or Market) × Week.
- Campaign N:1 Retailer. Campaign N:M Product.

**Lifecycles**
- *Trade promotion:* planned → budget-approved → agreed with retailer → in-market → post-evaluated → **settled** ∎. Or **cancelled** ∎.
- *Deduction:* taken → in research → matched/valid → **cleared** ∎. Or invalid → disputed → **repaid** ∎ / **written off** ∎.
- *Order (EDI):* PO received (850) → acknowledged (855) → shipped / ASN (856) → invoiced (810) → **paid** ∎. Or **cancelled** ∎ [10].
- *Item listing:* proposed → item data synced (GDSN) → authorised → on shelf → **delisted** ∎ [11].

**Processes & promises**
- Retailer on-time-in-full compliance programmes, with fines.
- Weekly syndicated-data refresh.
- Deduction dispute windows.
- Promo claim settlement.
- Item data synchronised before first order [11].

### Systems & standards

- **Systems:**
  - ERP: SAP S/4HANA.
  - TPM/TPO suites.
  - DSD route systems.
  - Retailer data portals.
  - Syndicated POS: NielsenIQ, Circana, SPINS.
  - Retail-media platforms of the big retailers.
  - EDI VANs.
- **Standards:**
  - **GS1** GTIN/GLN and **GDSN** item synchronisation [11].
  - **X12** transaction sets (850/855/856/810, plus 852 product activity) [10].
  - **IAB/MRC Retail Media Measurement Guidelines** [9].
  - The NIQ and Circana CPG dictionaries for measure names [1][3].

### Validation datasets

1. **dunnhumby "The Complete Journey"** [12].
   - Content: household-level transactions for 2,500 frequent-shopper households over two years at one retailer, with demographics, targeted campaigns, coupons and redemptions. Distributed via dunnhumby and the `completejourney` R package.
   - Licence: verify the dunnhumby source terms.
   - *Computes:* coupon and campaign response, basket metrics, brand vs private-label share, household penetration and repeat rate.
   - *Cannot compute:* sell-in, %ACV, trade spend.
2. **M5 Forecasting (Walmart)** [13].
   - Content: 3,049 products × 10 stores in 3 states × 1,941 days (42,840 hierarchical series), with weekly sell prices, calendar events and SNAP days. Licence per Kaggle competition rules.
   - *Computes:* per-store velocity, price elasticity from price changes, event and SNAP effects, OOS inference from zero runs (with caution).
3. **Corporación Favorita** (Kaggle) [14].
   - Content: 54 stores in Ecuador, about 125M rows, onpromotion flag, daily store transaction counts, oil price, holidays. Zero-sales rows are **omitted** and negative units are returns.
   - *Computes:* promo lift, traffic vs units, family/class mix.
   - *Caveat:* the data must be densified before computing velocity or OOS.

No public dataset joins manufacturer shipments to retailer POS, so sell-in vs sell-through cannot be validated end-to-end (see §16).

### What generic analytics gets wrong here

- It treats shipments (sell-in) as demand. Loading, forward buying and pipeline fill show up as fake growth followed by a fake decline.
- It explains sales with the wrong decomposition. The right one is distribution (TDP) × velocity × price, not "units went down".
- It measures promotions against actual pre-period sales instead of a modelled baseline. That ignores post-promo dips and cannibalisation, and yields a positive ROI for promotions that lose money [6].
- It mixes gross, net and net-net sales, while deductions arrive months late; account profitability is restated after the fact.
- It reports retail-media ROAS (attributed) as incremental return [9].

### Sources

- [1] NielsenIQ CPG Dictionary, Velocity ($/TDP): https://microsites.nielseniq.com/cpg-dictionary/dictionary/velocity-tdp/
- [2] NielsenIQ CPG Dictionary, TDP: https://microsites.nielseniq.com/cpg-dictionary/dictionary/total-distribution-points-tdp/
- [3] Circana CPG Dictionary, TDP: https://www.circana.com/liquid-data-go/cpg-dictionary/total-distribution-points-(tdp)
- [4] NIQ, "3 useful metrics to optimize your CPG trade promotion spend" (2022): https://nielseniq.com/global/en/insights/education/2022/3-useful-metrics-to-optimize-your-cpg-trade-promotion-spend/
- [5] NIQ CPG Dictionary, trade efficiency: https://microsites.nielseniq.com/cpg-dictionary/dictionary/trade-efficiency/
- [6] FoodNavigator, "Three-quarters of CPG promotions don't break even, says Nielsen" (2014): https://www.foodnavigator.com/Article/2014/10/09/Three-quarters-of-CPG-promotions-don-t-break-even-Nielsen/
- [7] Scout (aggregator), CPG trade spend benchmarks: https://www.cpgscout.ai/blog/cpg-trade-spend
- [8] Gruen, Corsten & Bharadwaj (2002), *Retail Out-of-Stocks: A Worldwide Examination*, GMA/FMI/CIES: https://www.supplychain247.com/images/pdfs/GMA_2002_Worldwide_OOS_Study.pdf
- [9] IAB/MRC Retail Media Measurement Guidelines (Jan 2024): https://www.iab.com/wp-content/uploads/2024/01/IAB_Retail_Media_Measurement_Guidelines_January2024.pdf · IAB release: https://www.iab.com/news/iab-and-mrc-releases-retail-media-measurement-guidelines/
- [10] X12: https://x12.org/
- [11] GS1 GDSN: https://www.gs1.org/services/gdsn · GLN: https://www.gs1.org/standards/id-keys/gln · GLN Allocation Rules: https://www.gs1.org/standards/gs1-gln-allocation-rules-standard/current-standard
- [12] completejourney R package vignette: https://cran.r-project.org/web/packages/completejourney/vignettes/completejourney.html · study using the data: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6238299/
- [13] Makridakis et al., "M5 accuracy competition" (IJF): https://www.sciencedirect.com/science/article/pii/S0169207021001874
- [14] Kaggle Favorita: https://www.kaggle.com/c/favorita-grocery-sales-forecasting/data

---

## 4. Grocery & convenience retail (incl. online grocery and quick commerce)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Identical / comparable sales** (IDs, comps, LFL) | Kroger: sales at supermarkets in operation 5 full quarters without expansion or relocation, **excluding fuel** [1] | Store × period, eligible stores only | Company-specific rule. Always state the rule | Including new, remodelled or relocated stores. Fuel price swings. 53-week years and holiday shifts. |
| **Traffic × basket** (transactions, AOV, items per basket) | Net sales ÷ transactions. Units ÷ transactions | Transaction (basket) | Online reference: Instacart FY2024 AOV $114 (GTV-based, incl. tips and fees) [2] | Counting line items as transactions. Netting returns inside baskets. Random-weight units vs item counts. |
| **Shrink** | Inventory loss (theft, damage, admin error, spoilage) ÷ sales, at retail value | Store × department × period | All retail FY2022: 1.6% of sales ($112.1B), NRF NRSS 2023 [3] | Mixing cost and retail valuation. Spoilage included in one store, excluded in another. Known vs unknown shrink conflated. |
| **On-shelf availability · OOS** | SKU-store-days unavailable ÷ SKU-store-days | SKU × store × day | 8.3% worldwide (2002) [4] | Zero-sales inference on slow movers. Phantom inventory. |
| **Net profit margin** | Net income after tax ÷ sales | Company-year | US food retail 2023: 1.6% after tax, lowest since 2019 (FMI) [5] | Benchmarking a grocer against specialty-retail margins. Vendor funds and LIFO effects hidden in COGS. |
| **Gross margin · markdown · waste (fresh)** | (Sales − COGS) ÷ sales. Markdown $ ÷ sales. Waste units ÷ received units | Department × store × week | No verified public benchmark | Treating vendor scan-back funding inconsistently. Waste recorded as shrink in some stores and as markdown in others. |
| **Online grocery: GTV, orders, take rate, ads % of GTV** | Instacart GTV = value of products sold incl. taxes, deposits, fees, **tips** and subscription fees. Order = completed transaction primarily from one retailer. FY2024: GTV $33.46B, 294.0M orders, AOV $114, transaction revenue 7.2% of GTV, advertising & other 2.9% [2] | Order | As cited [2] | Comparing tip-inclusive GTV with retailer net sales. |
| **Quick commerce: NOV, EBITDA % of NOV, store count** | NOV = GOV less discounts (Eternal) [6]. Blinkit Q2FY26: 1,816 stores (+272 net), adjusted EBITDA −1.3% of NOV (from −1.8%), ~80% of NOV on own-inventory model [7] | Dark store × day. Order | As cited [7] | Moving from marketplace to inventory ownership lifts *revenue* mechanically: Eternal adjusted revenue +172% YoY vs +65% like-for-like [7]. Compare NOV, not revenue. |
| **Fulfilment quality** (pick accuracy, substitution rate, on-time, delivery time) | Correct picks ÷ ordered items. Substituted ÷ ordered items. On-time ÷ delivered orders | Order line / order | No verified public benchmark | Measuring delivery time on completed orders only (survivor bias). Promised window vs actual not stored. |
| **Repeat · reorder behaviour** | Share of items reordered. Days between orders | Customer × order | Instacart public data caps days_since_prior_order at 30 [8] | Treating the 30-day cap as a real value. |

### Playbook

1. **Comparable sales fall.** Split into traffic vs basket, then check in order:
   1. Traffic by daypart and store cluster.
   2. Price index vs competitors.
   3. Units per basket.
   4. OOS on key value items [4].
   5. Promo calendar lapping.
   6. Competitor openings.
   7. Weather and holiday shifts.
   8. Benefit-payment timing (SNAP days are visible in M5).

   *Action:* key-value-item price investment, OOS recovery, targeted promotions.
2. **Gross margin falls.** Check in order:
   1. Mix shift.
   2. Shrink and waste rising.
   3. Markdown depth.
   4. Vendor funding shortfall vs plan.
   5. Deliberate price investment.

   *Action:* markdown optimisation, vendor-funding recovery, assortment rationalisation.
3. **Shrink rises.** Check in order:
   1. Department: fresh spoilage vs theft vs admin error [3].
   2. Receiving errors and DSD vendor credits.
   3. Count accuracy.
   4. Date-code rotation.

   *Action:* ordering parameters, loss-prevention measures, receiving audits.
4. **Online orders rise but contribution per order falls.** Check in order:
   1. AOV (small baskets).
   2. Fee waivers and subscription mix.
   3. Picker productivity.
   4. Substitutions and refunds.
   5. Delivery distance and batching.

   *Action:* basket minimums, batching, slotting changes.
5. **Quick-commerce EBITDA % of NOV worsens.** Check in order:
   1. Orders per store per day, by store-age cohort — new stores dilute [7].
   2. AOV.
   3. Discount depth (GOV vs NOV gap) [6].
   4. Rider cost per order.
   5. Wastage.
   6. Assortment non-grocery share [6].

   *Action:* slow openings, rebalance assortment, adjust delivery radius and fees.

### Ontology sketch

**Objects (20).** Store (format: supermarket / convenience / fuel / dark store) · Department/Category · Item (SKU, GTIN, PLU, random-weight) · Price (regular / promo) · Promotion · Inventory Position (item × store) · Perishable Lot · Supplier/DSD vendor · Purchase Order · Goods Receipt · Transaction (basket) · Transaction Line · Tender (incl. EBT/SNAP) · Loyalty Customer · Shrink Event (waste / markdown / theft / count adjustment) · Online Order · Order Line · Substitution · Pick Task · Delivery Trip · Delivery Slot.

**Links**
- Store 1:N Inventory Position N:1 Item.
- Transaction N:1 Store. Transaction N:0..1 Loyalty Customer. Transaction 1:N Line N:1 Item.
- Line N:0..1 Promotion. Transaction 1:N Tender.
- PO N:1 Supplier. PO 1:N Goods Receipt.
- Online Order N:1 Customer. Online Order N:1 fulfilling Store. Online Order 1:N Order Line.
- Order Line 1:0..1 Substitution. Order 1:N Pick Task.
- Delivery Trip 1:N Order (batching).
- Shrink Event N:1 Item × Store.

**Lifecycles**
- *Online order:* placed → accepted → picking → packed → out for delivery / ready for pickup → **delivered / collected** ∎. Or **cancelled** ∎; or failed delivery → **refunded** ∎.
- *Perishable lot:* received → on shelf → marked down → **sold** ∎ / **wasted** ∎.
- *PO:* created → transmitted → confirmed → received (partial)* → invoiced → **closed** ∎.
- *Item:* new → active → **discontinued** ∎.

**Processes & promises**
- Delivery promise: slot window, or minutes for quick commerce.
- Substitution consent.
- Shelf-price vs POS price accuracy.
- Date-code rotation.
- Benefit-tender eligibility rules.

### Systems & standards

- **Systems:**
  - POS: NCR Voyix, Toshiba.
  - Merchandising/ERP: SAP, Oracle Retail.
  - Forecasting and replenishment: RELEX, Blue Yonder.
  - WMS for DCs and dark stores.
  - E-commerce and marketplace platforms: Instacart, retailer sites.
  - Loyalty, electronic shelf labels, rider dispatch apps.
- **Standards:**
  - **GS1** GTIN/GLN/GDSN (§3 [11]).
  - **X12** EDI (§3 [10]).
  - Company KPI definitions as the naming quarry: Kroger identical sales, Instacart GTV/Orders, Eternal NOV [1][2][6].

### Validation datasets

1. **Instacart Online Grocery Shopping Dataset 2017** [8].
   - Content: 3M+ orders from 200k+ users (4–100 orders each), with order day-of-week and hour, days_since_prior_order (capped at 30), aisle/department and reordered flag.
   - Licence: non-commercial, under Instacart's terms.
   - *Computes:* basket size, reorder rate, inter-order time, department mix, affinity.
   - *Cannot compute:* prices, GTV, fulfilment times.
2. **Corporación Favorita** (§3 [14]).
   - *Computes:* store traffic (transactions) vs units, promo lift, perishables flag, holiday effects.
3. **M5 Walmart** (§3 [13]).
   - *Computes:* SNAP-day effects, price elasticity, store/state velocity.
4. **dunnhumby Complete Journey** (§3 [12]).
   - *Computes:* loyalty-household penetration, coupon redemption, shrink-free basket economics.

No public dataset covers shrink or dark-store operations (see §16).

### What generic analytics gets wrong here

- It computes comps across all stores, including new, relocated and remodelled ones, and often fuel.
- It averages daily sales from data where zero-sales rows are missing (Favorita), which biases velocity up and hides OOS.
- It compares online GTV (tips, fees, taxes) with store net sales. It reads a marketplace-to-inventory model change as revenue growth [7].
- It treats spoilage, markdown and theft as one "shrink" number valued inconsistently at cost and retail [3].
- It benchmarks grocery margins against other retail: net margin around 1.6% is normal [5].

### Sources

- [1] Kroger 10-K (identical sales definition): https://www.sec.gov/Archives/edgar/data/56873/000155837018002753/kr-20180203x10k.htm · FY2025 release: https://www.sec.gov/Archives/edgar/data/56873/000110465926023800/tm267907d1_ex99-1.htm
- [2] Maplebear (Instacart) Q4 2024 shareholder letter: https://www.sec.gov/Archives/edgar/data/1579091/000157909125000009/cartfourthquarter2024sha.htm
- [3] NRF National Retail Security Survey 2023: https://nrf.com/research/national-retail-security-survey-2023 · press release: https://nrf.com/media-center/press-releases/shrink-accounted-over-112-billion-industry-losses-2022-according-nrf
- [4] GMA/FMI/CIES 2002 OOS study: https://www.supplychain247.com/images/pdfs/GMA_2002_Worldwide_OOS_Study.pdf
- [5] Grocery Dive, FMI margins: https://www.grocerydive.com/news/grocery-industry-profit-margins-fall-to-pre-pandemic-levels-fmi/720517/ · FMI Food Industry Facts: https://www.fmi.org/our-research/food-industry-facts
- [6] Eternal Q4FY26 shareholders' letter (NOV = GOV less discounts; GOV inflation caveat): https://b.zmtcdn.com/investor-relations/Eternal_Limited_Shareholders_Letter_Q4FY26_Results.pdf · blog: https://www.eternal.com/blog/q4fy26/ (as summarised)
- [7] Eternal Q2FY26 shareholders' letter (pages 2–3 read): https://b.zmtcdn.com/investor-relations/Eternal_Shareholders_Letter_Q2FY26_Results.pdf
- [8] Instacart, "3 Million Instacart Orders, Open Sourced": https://tech.instacart.com/3-million-instacart-orders-open-sourced-d40d29ead6f2 · Kaggle: https://www.kaggle.com/datasets/psparks/instacart-market-basket-analysis

---

## 5. Restaurants / QSR / food service

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Comparable sales** (same-store sales, comps) | McDonald's: % change in sales for all restaurants (company-operated **and** franchised) open ≥13 months, including temporarily closed ones; excludes currency translation and hyperinflationary markets [1]. Chipotle: company-owned restaurants open ≥13 full calendar months [2] | Restaurant × period, eligible units only | Company rule. State it explicitly | Including honeymoon units under 13 months. Mixing company-owned with systemwide bases. Reporting comps without the traffic × average check split. |
| **Systemwide sales** | Sales at all restaurants incl. franchised. Not company revenue; franchise royalties are computed on it [1] | Restaurant × period | — | Treating systemwide sales as revenue. |
| **AUV / average restaurant sales** | Chipotle: trailing-12-month food & beverage revenue of company-owned restaurants open ≥12 full calendar months [2] | Restaurant-year | Company-specific | Including partial-year units. Pooling formats (drive-thru vs in-line). |
| **Restaurant-level operating margin** (four-wall margin) | (Total revenue − direct restaurant operating costs) ÷ total revenue [2] | Restaurant × period | Company-specific | Allocating G&A inconsistently. Mixing franchised units (royalty) with company units (P&L). |
| **Food & beverage cost %** (COGS %) | Food & non-alcohol beverage cost ÷ sales | Restaurant × period | NRA 2024 medians: limited-service 32.4%, full-service 32.0%. Full-service ≥$2M sales 31.0% vs <$2M 33.7% [3][4] | Purchases-based vs inventory-based costing. Waste, comps and voids hidden. Menu-mix shifts read as inflation. |
| **Labour cost %** | Salaries, wages and benefits ÷ sales | Restaurant × period | NRA 2024 medians: full-service 36.5% (34.2% for profitable operators); limited-service 31.7% (30.0% profitable, 34.1% loss-making) [5] | Excluding benefits and payroll taxes. Salaried managers left out. Tips passed through as wages. |
| **Prime cost** | (Food & beverage cost + total labour) ÷ sales | Restaurant × period | Build per restaurant, then take percentiles. Median food % + median labour % ≠ median prime cost [3][5] | **Adding medians.** Mixing cost and sales periods (weekly labour vs monthly inventory). |
| **Occupancy cost %** | Rent, CAM, property tax, insurance ÷ sales | Restaurant-year | NRA 2024: more than 5% of sales [6] | Ignoring percentage rent and landlord allowances. |
| **RevPASH** | Revenue ÷ (available seats × hours open), by daypart [7][8] | Restaurant × daypart | Venue-specific | Counting unusable seats (closed patio). Whole-day hours instead of daypart. |
| **Speed of service · order accuracy** (drive-thru) | Total time from arrival in the lane to departure; share of orders accurate | Visit | Intouch Insight 2025, 13 QSR brands: average total time 4 min 15 s (10 s slower than 2024); accuracy 87% (from 89%) [9] | Measuring window time only (excludes queue). Ignoring park-outs and remakes. |

### Playbook

1. **Comparable sales fall.** Split into traffic (transactions) × average check, then check in order:
   1. Traffic by daypart and channel: dine-in, drive-thru, kiosk, app, third-party delivery.
   2. Check split: price vs mix vs items per order.
   3. Lapping last year's promotion or LTO.
   4. Peak throughput — lost cars when the lane is slow [9].
   5. Menu availability (86'd items).
   6. Local competition, weather, calendar.

   *Action:* value menu or price-pack, peak staffing, LTO, local marketing.
2. **Prime cost rises.**
   - *Food side, check in order:* commodity inflation → waste → portioning → comps/voids → menu mix.
   - *Labour side, check in order:* scheduled vs actual hours vs forecast accuracy → overtime → wage rate → turnover and training hours [5].

   *Action:* menu engineering, price, order guides, schedule to forecast.
3. **Drive-thru time rises.** Check in order:
   1. Order-taking time vs wait at window vs queue.
   2. New menu complexity (LTOs).
   3. Peak staffing.
   4. Remakes from accuracy errors [9].

   *Action:* staffing, menu simplification, order-ahead lanes.
4. **Restaurant-level margin falls while comps rise.** Check in order:
   1. Mix toward third-party delivery (commissions).
   2. Discounting and loyalty redemptions.
   3. Wage inflation.
   4. Occupancy costs on new leases [6].

   *Action:* delivery menu pricing, loyalty rebalancing.
5. **New units open below plan AUV.** Check in order:
   1. Cohort ramp vs prior openings.
   2. Trade area and format (drive-thru or not).
   3. Cannibalisation of nearby units.
   4. Launch marketing.

   *Action:* local marketing, tighten site criteria.

### Ontology sketch

**Objects (22).** Brand/Concept · Restaurant (company-owned or franchised) · Franchisee · Daypart · Menu · Menu Item · Modifier · Recipe (bill of materials) · Ingredient/Inventory Item · Supplier/Distributor · Supplier Invoice · Check (ticket/order) · Check Line · Payment (incl. tip) · Channel · Table/Seat · Reservation · Guest/Loyalty Member · Employee · Shift (scheduled, actual) · Inventory Count · Waste Log · Third-party Delivery Order.

**Links**
- Brand 1:N Restaurant. Restaurant N:0..1 Franchisee.
- Restaurant 1:N Check N:1 Channel.
- Check 1:N Line N:1 Menu Item. Line 1:N Modifier.
- Menu Item 1:1 Recipe 1:N Ingredient.
- Check 1:N Payment. Check N:0..1 Table. Check N:0..1 Loyalty Member.
- Reservation N:1 Guest. Reservation 1:0..1 Check (when seated).
- Shift N:1 Employee. Shift N:1 Restaurant.
- Supplier Invoice N:1 Supplier. Waste Log N:1 Ingredient or Menu Item.

**Lifecycles**
- *Check:* opened → fired to kitchen → served/handed off → paid → **closed** ∎. Or **voided** ∎ / **refunded** ∎. Comps are partial adjustments.
- *Digital / third-party order:* placed → accepted → in prep → ready → courier pickup → **delivered** ∎. Or **rejected / cancelled** ∎; post-delivery adjustments (missing item refunds).
- *Reservation:* booked → confirmed → seated → **completed** ∎. Or **cancelled** ∎ / **no-show** ∎.
- *Restaurant unit:* pipeline → construction → opened → enters comp base (13 months) → [remodel/relocation leaves comp base] → **closed** ∎ / **refranchised** ∎.
- *Shift:* scheduled → clocked in → **clocked out** ∎. Or **no-show** ∎.

**Processes & promises**
- Brand speed-of-service targets.
- Quoted pickup times.
- Reservation hold times.
- Food-safety hold-time and temperature logs.
- Third-party prep-time commitments.
- Royalty and ad-fund remittance.

### Systems & standards

- **Systems:**
  - POS: Toast, Oracle Simphony, NCR Aloha, Square.
  - Kitchen display systems.
  - Back office and inventory: Restaurant365, CrunchTime.
  - Scheduling: 7shifts, HotSchedules.
  - Reservations: OpenTable, Resy, SevenRooms.
  - Online ordering: Olo.
  - Aggregators: DoorDash, Uber Eats.
  - Loyalty and CRM.
  - Broadline distributors (Sysco, US Foods) invoicing by EDI.
- **Standards:**
  - No dominant open data standard for restaurant POS data.
  - Naming quarry: company KPI definitions (McDonald's, Chipotle) [1][2]; the NRA Restaurant Operations measures [3]–[6]; RevPASH (Kimes/HSMAI) [7][8].
  - Supply side: GS1 and X12 (see §3).

### Validation datasets

1. **Recruit Restaurant Visitor Forecasting** (Kaggle, 2018) [10].
   - Content: Japanese restaurants on two systems. AirREGI (POS and reservations) has daily visitors and reservations with both reservation and visit timestamps. Hot Pepper Gourmet has reservations. Plus store genre, area and holidays. Licence: Kaggle competition rules (verify).
   - *Computes:* covers by day and daypart, reservation lead time, reservation-to-visit ratio (walk-in share), seasonality and holidays, genre/area comparisons.
   - *Cannot compute:* sales, check average, food or labour cost.
2. **No public dataset combining check-level POS with labour and food cost was found.** Prime-cost and margin playbooks need design-partner data (§16).

### What generic analytics gets wrong here

- It adds median food-cost % and median labour-cost % to produce an "industry prime cost". Medians do not add.
- It computes comps on all units, including honeymoon units, or mixes company-owned with systemwide sales.
- It explains comps with average check only, skipping the traffic × check split and price vs mix within the check.
- It treats franchised systemwide sales as company revenue.
- It measures drive-thru speed at the window only, ignoring queue time and accuracy remakes [9].

### Sources

- [1] McDonald's 10-K FY2024: https://www.sec.gov/Archives/edgar/data/63908/000006390825000012/mcd-20241231.htm
- [2] Chipotle Q4/FY2024 results (definitions): https://ir.chipotle.com/2025-02-04-CHIPOTLE-ANNOUNCES-FOURTH-QUARTER-AND-FULL-YEAR-2024-RESULTS
- [3] NRA, food cost ratios 2024: https://restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/restaurant-operators-kept-food-cost-ratios-in-check-in-2024/
- [4] NRA, higher-volume restaurants' food-cost ratios 2024: https://www.restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/higher-volume-restaurants-reported-lower-food-cost-ratios-in-2024/
- [5] NRA, labour costs 2024: https://restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/elevated-labor-costs-had-a-significant-impact-on-restaurant-profitability-in-2024/
- [6] NRA, occupancy costs 2024: https://www.restaurant.org/research-and-media/research/restaurant-economic-insights/analysis-commentary/restaurant-occupancy-costs-were-more-than-5-of-sales-in-2024/
- [7] HSMAI Academy, RevPASH: https://academy.hsmai.org/glossary/revpash/
- [8] Kimes, *Restaurant Revenue Management* (Cornell eCommons): https://ecommons.cornell.edu/entities/publication/779ca191-03a2-4abe-8e4b-2de7fdd4f7ff
- [9] Intouch Insight 2025 Drive-Thru Study: https://www.intouchinsight.com/press-releases/drive-thru-study-2025-press-release · QSR Magazine: https://www.qsrmagazine.com/story/the-2025-qsr-drive-thru-report/
- [10] Kaggle, Recruit Restaurant Visitor Forecasting: https://www.kaggle.com/c/recruit-restaurant-visitor-forecasting · file descriptions: https://github.com/kasuo46/Restaurant_Visitor_Forecasting

---

## 6. Media & streaming / digital publishing

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Paid subscribers** (paid memberships, net/gross adds) | Accounts on an active paid plan at period end. Spotify counts **every Family/Duo sub-account** and subscribers in a **grace period of up to 30 days** after a failed payment [1] | Account (or sub-account) × day | Netflix stopped reporting memberships and ARM from 2025 [2][3] | Mixing households, accounts and profiles. Counting trials and grace-period accounts as paying without saying so. |
| **MAU / DAU** | Spotify MAU: ad-supported users + Premium subscribers who consumed content for **>0 ms in the last 30 days**; may overstate unique individuals [1] | User × day (30-day rolling) | — | Rolling 30 days vs calendar month. Duplicate accounts. Bots. |
| **ARPU / ARM** | Netflix ARM = streaming revenue ÷ average paid memberships ÷ months [2]. Spotify Premium ARPU = quarterly Premium revenue ÷ average **daily** Premium subscribers ÷ 3 [1] | Subscriber-month | Company-specific; compare FX-neutral | Dividing by end-of-period subscribers. Reading family-plan or market-mix dilution as a price cut. |
| **Churn** (gross, net) | Gross: cancellations in the month ÷ subscribers at start. Net: nets out resubscriptions | Subscriber-month | Antenna, US premium SVOD: weighted-average monthly churn about 5% since Jan 2023. Sep 2024: gross 5.3% vs net 3.1% [4][5]. 2025: steady ~4.6% (as summarised) [6]. About 34% of gross adds (57M of 169M, Sep 2023–Aug 2024) were resubscribers (as summarised) [4] | Simple average of churn across services or months — weight it. Counting resubscribers as new customers. Mixing annual and monthly plans. |
| **Engagement time · share of TV** | Hours viewed per title or person. Share of total TV usage: streaming vs cable vs broadcast [7] | Person × day; title × week | Nielsen The Gauge, monthly [7] | Comparing "views" with hours. Mixing panels and methodologies. |
| **Video ad viewability · completion** | MRC video viewable: ≥50% of pixels in view for ≥2 continuous seconds [8]. Completion = completes ÷ starts, from VAST quartile events [9] | Ad impression | Standard thresholds [8] | Counting served impressions as viewable. Completion divided by impressions instead of starts. |
| **Content cost per hour viewed** | Content amortisation ÷ hours viewed | Title × period | No public benchmark | Using cash spend instead of amortisation. |
| **Paying-reader share · subscription conversion** (publishing) | Paying subscribers ÷ registered users or monthly uniques | User-month | Reuters Institute DNR 2025, population survey: 18% pay for online news across 20 richer countries; Norway 42%, US 20%, Croatia 6% [10] — **not** a site conversion rate | Using survey share as funnel conversion. Counting bundled or gifted subscriptions as paid. |
| **RPM / ad yield** (publishing) | Ad revenue ÷ pageviews × 1,000 | Page / session | No verified public benchmark | RPM per pageview vs per session. IVT not filtered. |

### Playbook

1. **Net subscriber adds fall.** Split into gross adds vs churn, then check in order:
   1. Content slate vs last year.
   2. Price-change timing.
   3. Trial and promo cohorts ending.
   4. Involuntary churn: payment failures and grace-period expiries [1].
   5. Bundle and partner changes.
   6. Competitor tentpoles.

   *Action:* release scheduling, win-back offers, payment-retry tuning.
2. **Churn rises.** Cut by:
   1. Tenure cohort.
   2. Plan (ad tier vs premium).
   3. Acquisition source (promo cohorts).
   4. Voluntary vs involuntary.
   5. Post-tentpole exits by serial churners [4].

   *Action:* annual plans, content cadence, save offers.
3. **ARPU falls.** Check in order:
   1. Plan mix: ad tier, family.
   2. Geographic mix.
   3. Promotions.
   4. FX.
   5. Price-rise lag.

   *Action:* upsell, pricing, ad-tier monetisation.
4. **Engagement hours fall.** Check in order:
   1. Top-title performance vs last year.
   2. App or device release defects.
   3. Recommendation or UI changes.
   4. Seasonality.
   5. Measurement changes [7].

   *Action:* roll back, re-programme.
5. **Publisher ad revenue falls.** Split pageviews × RPM, then check in order:
   1. Referral traffic mix (search, social).
   2. Consent rates.
   3. Viewability [8].
   4. IVT filtering.
   5. Fill and CPM seasonality.

   *Action:* SEO, ad-layout changes, direct deals.

### Ontology sketch

**Objects (19).** Account/Household · Profile · Subscription · Plan/Price · Invoice/Billing Event · Payment Attempt · Promotion/Trial · Device · Title (movie, series → season → episode) · Asset/Rendition · Rights Window/Licence · Viewing Session · Playback Event · Ad Break · Ad Impression · Campaign · (music) Track / Release / Royalty Statement · (publishing) Article · Paywall Event.

**Links**
- Account 1:N Profile.
- Account 1:N Subscription (sequential over time). Subscription N:1 Plan.
- Subscription 1:N Invoice 1:N Payment Attempt. Subscription N:0..1 Promotion.
- Profile 1:N Session N:1 Title.
- Episode N:1 Season N:1 Series.
- Title 1:N Rights Window (territory × dates). Title 1:N Asset.
- Session 1:N Ad Impression N:1 Campaign.
- Track N:M Release. Stream N:1 Track.

**Lifecycles**
- *Subscription:* trial → active → [past-due / grace, ≤30 days at Spotify [1]] → cancel-pending (active to period end) → **churned** ∎. A resubscribe creates a new Subscription on the same Account. Pause is a side state.
- *Rights window:* acquired → in production → live → expiring → **removed** ∎.
- *Ad impression:* requested → served → viewable → quartiles → **complete** ∎. Or **filtered as IVT** ∎.
- *Article:* draft → published → updated* → **archived** ∎.

**Processes & promises**
- Dunning retry schedule.
- Cancellation effective at period end.
- Content live by window start.
- Royalty reporting cadence (DDEX DSR) [12].
- Ad make-goods against delivery guarantees.

### Systems & standards

- **Systems:**
  - Subscription billing: Zuora, Recurly, in-house.
  - App-store in-app subscriptions.
  - Player QoE analytics: Conviva, Mux.
  - CMS/MAM and rights management.
  - Ad serving and SSAI: Google Ad Manager, FreeWheel.
  - Audience measurement: Nielsen.
  - CRM.
- **Standards:**
  - **EIDR** identifiers for titles, versions, seasons and episodes [11].
  - **DDEX** (ERN release notification, DSR sales/usage reporting, MWN musical works) [12].
  - **IAB Tech Lab VAST 4.3** [9].
  - **MRC viewability** [8].
  - Company definitions from Spotify and Netflix filings [1][2].

### Validation datasets

1. **KKBox Churn Prediction Challenge** (WSDM Cup 2018) [13].
   - Content: music-streaming subscriptions — members; transactions (plan days, list vs actual price, auto-renew, cancel flag, transaction and expiry dates); about 30 GB of daily listening logs. Churn = no new valid subscription within 30 days of expiry. Licence: competition rules (verify).
   - *Computes:* gross churn, auto-renew vs manual, cancel vs lapse, discounting (paid vs list price), engagement-before-churn curves.
2. **MIND — Microsoft News Dataset** [14].
   - Content: 1M users, ~160k articles, 15M+ impression logs (Oct 12–Nov 22, 2019). Microsoft Research License (non-commercial).
   - *Computes:* CTR by article and category, engagement cohorts, recommendation lift.
3. **MovieLens 32M** [15].
   - Content: ratings and tags. Commercial use needs GroupLens permission.
   - *Computes:* catalogue long-tail and engagement proxies only — no subscriptions.

### What generic analytics gets wrong here

- It counts family sub-accounts, grace-period and trial users as paying without saying so, and divides revenue by end-of-period subscribers [1].
- It simple-averages churn across services or months, and treats resubscribers (about a third of gross adds [4]) as new customers.
- It reads an ARPU decline as a price cut when the plan or market mix shifted.
- It treats MAU (>0 ms in 30 days) as unique people [1].
- It counts served impressions as viewable, and divides completions by impressions rather than starts [8][9].

### Sources

- [1] Spotify 20-F FY2024 (MAU, Premium Subscribers, Premium ARPU definitions): https://www.sec.gov/Archives/edgar/data/1639920/000163992025000003/ck0001639920-20241231.htm
- [2] Netflix 10-K FY2025: https://www.sec.gov/Archives/edgar/data/1065280/000106528026000034/nflx-20251231.htm
- [3] CNBC on Netflix ending subscriber reporting: https://www.cnbc.com/2024/04/18/netflix-earnings-what-subscriber-reporting-change-means.html
- [4] Antenna, 2024 Top Subscription Insights — Net Churn: https://www.antenna.live/insights/antennas-2024-top-subscription-insights-net-churn · A Case for Rethinking Churn: https://www.antenna.live/insights/a-case-for-rethinking-churn
- [5] Antenna, Checking In On Premium SVOD Churn: https://www.antenna.live/insights/checking-in-on-premium-svod-churn
- [6] Deadline, Antenna data (June 2025): https://deadline.com/2025/06/antenna-streaming-data-stable-growth-ad-tiers-subscriber-churn-1236442624/
- [7] Nielsen, The Gauge: https://www.nielsen.com/data-center/the-gauge/
- [8] MRC Viewable Ad Impression Measurement Guidelines: https://www.iab.com/wp-content/uploads/2015/06/MRC-Viewable-Ad-Impression-Measurement-Guideline.pdf
- [9] IAB Tech Lab VAST: https://iabtechlab.com/standards/vast/
- [10] Reuters Institute Digital News Report 2025, executive summary: https://reutersinstitute.politics.ox.ac.uk/digital-news-report/2025/dnr-executive-summary
- [11] EIDR: https://www.eidr.org/
- [12] DDEX: https://ddex.net/
- [13] KKBox churn challenge: https://www.kaggle.com/c/kkbox-churn-prediction-challenge · paper using it: https://arxiv.org/pdf/1802.03396
- [14] MIND: https://msnews.github.io/ · Azure Open Datasets: https://learn.microsoft.com/en-us/azure/open-datasets/dataset-microsoft-news
- [15] MovieLens 32M README (usage licence): https://files.grouplens.org/datasets/movielens/ml-32m-README.html

---

## 7. Gaming (mobile F2P and premium)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Day-N retention** (D1, D7, D28/D30) | Share of an install cohort active on day N after install. State classic (exactly day N) vs rolling (day N or later) | Install cohort × N | **GameAnalytics, 2024 mobile data (11,600 games)** [1]: D1 top quartile 26.48–27.69%, bottom quartile 10–11.5%; iOS top quartile 31–33% vs Android 25–27%. D7 median 3.42–3.94% (2023 median ~4–5%), top quartile 7–8%. 75% of games stay below 3% at D28. **2025 data** [2]: mobile D1 median ~22% (top quartile just above 30%), D7 median just under 4% (top 6–7%), D30 median 0.68–0.79% (top 1.6–1.8%). PC D1 median ~7%, D7 1.1–1.3%, D30 ~0.2–0.25%. *Drivers:* genre, platform, region, paid vs organic installs | Averaging retention across cohorts of different size (pool users instead). Classic vs rolling confusion. Device-level vs account-level (reinstalls). Timezone-shifted "days". |
| **DAU · MAU · stickiness** (DAU/MAU) | Average daily uniques ÷ monthly uniques | User × day | PC 2025: DAU/MAU median 4–5%, top quartile ~7% [2]. Mobile: not published in the reports read | Launch-spike months. Summing DAU across platforms double-counts cross-platform players. |
| **Session length · sessions/day · daily playtime** | From session start/end events, with a declared inactivity timeout | Session / user-day | 2024 mobile: session median 5–6 min, sessions/day median 4, playtime median ~22 min [1]. 2025 mobile: playtime median ~12 min, session median 3.1–3.5 min, sessions/day 3.8–3.9 [2]. **Samples differ by report year — do not trend across reports** | SDK timeout changes silently split or merge sessions. Means dominated by bots and whales. |
| **Payer conversion** | Unique payers ÷ active users in the period (or ÷ installs by day N, per cohort) | User × period / cohort | No authoritative free benchmark verified. GameAnalytics' 2025 and 2026 public reports publish no monetisation figures [1][2] | Denominator ambiguity (DAU vs MAU vs installs). Refunds and chargebacks. Ad watchers counted as payers. |
| **ARPDAU** | (Net IAP revenue + ad revenue) ÷ DAU for the day | Day | None verified | Gross vs net of store fees. Ads in or out. Averaging daily ARPDAUs over a month instead of revenue ÷ DAU-days. |
| **ARPPU** | Revenue ÷ paying users | Period | None verified | Mean driven by whales. Report percentiles. |
| **Cohort LTV · ROAS** | Cumulative cohort revenue by day N ÷ installs. Cohort revenue ÷ UA spend (per campaign) | Install cohort × campaign | None verified | Extrapolated LTV presented as actual. Right-censored young cohorts. Blending organic and paid cohorts. |
| **Progression funnel** (level/gate reach, drop-off) | Share of players reaching level N. Churn at gates | Player × level | Dataset-derived (Cookie Cats gate 30 vs 40) [3] | Survivorship: analysing only players who reached the level. |

### Playbook

1. **D1 retention falls.** Check in order:
   1. Install mix by UA source, campaign, geo and platform — low-intent paid traffic.
   2. Build: crash rate, load time.
   3. FTUE/tutorial step funnel.
   4. Device/OS segment.
   5. Store-listing changes (expectation mismatch).

   *Action:* pause campaigns, hotfix, FTUE redesign.
2. **Revenue falls.** Split into DAU × ARPDAU, with ARPDAU = payer conversion × ARPPU (+ ad ARPDAU). Check in order:
   1. DAU by cohort age: new vs veteran players.
   2. Payer conversion by segment.
   3. Top-spender (whale) revenue.
   4. LiveOps event/offer calendar vs last year.
   5. Price points, store fees, FX.
   6. Ad fill and eCPM, for ad-monetised games.

   *Action:* LiveOps events, offer tuning, high-value player CRM.
3. **D7/D30 retention falls after an update.** Check in order:
   1. Progression difficulty and gate placement — Cookie Cats: moving the first gate from level 30 to 40 changed D7 retention significantly, not D1 [3].
   2. Economy changes.
   3. Content cadence.
   4. Matchmaking.

   *Action:* roll back or tune, A/B test.
4. **ROAS (LTV ÷ CPI) deteriorates.** Check in order:
   1. CPI inflation vs cohort quality.
   2. Geo mix.
   3. Creative fatigue.
   4. Attribution/measurement changes.
   5. LTV-model drift.

   *Action:* bid caps, creative refresh, re-fit LTV curves.
5. **Sessions/day falls while playtime is flat.** Check instrumentation first: an SDK session-timeout change can do this. Then notification changes and energy/timer mechanics.

### Ontology sketch

**Objects (20).** Game/Title · Build (app version) · Platform/Store · Player (account) · Install/Device · Character/Avatar · Session · Telemetry Event · Level/Quest · Match · Item (virtual good) · Currency Wallet · Store Offer/SKU · Purchase (IAP) · Ad Impression (rewarded/interstitial) · LiveOps Event/Season/Battle Pass · UA Campaign/Ad Network · Experiment/Variant · Guild/Clan · Crash Report.

**Links**
- Player N:M Install/Device (over time). Install N:1 UA Campaign (attributed).
- Player 1:N Session 1:N Event. Session N:1 Build.
- Player N:M Level (progress records). Match N:M Player.
- Purchase N:1 Player. Purchase N:1 Offer.
- Wallet 1:1 (Player × Currency). Item N:M Player (inventory).
- Player N:0..1 Guild. Player N:1 Variant (per Experiment).

**Lifecycles**
- *Player:* installed → first open → tutorial complete → active → lapsed (N days inactive) → **churned** ∎. Reactivation re-enters active.
- *Payer state:* non-payer → converted → repeat payer.
- *Purchase:* initiated → store-authorised → receipt validated → **fulfilled** ∎. Or **failed** ∎ / **refunded or charged back** ∎.
- *Season / battle pass:* announced → live → ended → **rewards granted** ∎.
- *Match:* queued → matched → in progress → **completed** ∎. Or **abandoned** ∎.

**Processes & promises**
- Store payout schedule and platform fee.
- Receipt validation before item grant.
- Content/LiveOps cadence.
- Server uptime and latency objectives.
- Jurisdiction-specific disclosures (e.g. randomised items).

### Systems & standards

- **Systems:**
  - Engines: Unity, Unreal.
  - Game analytics: GameAnalytics, Unity Analytics, PlayFab.
  - Attribution (MMPs): AppsFlyer, Adjust.
  - Ad mediation: AppLovin MAX, Unity LevelPlay.
  - Store consoles: Apple App Store Connect, Google Play Console, Steamworks.
  - Payments/receipt validation.
- **Standards:**
  - No open standard for game telemetry exists; event taxonomies are vendor-defined. Quarry them from the analytics SDK in use.
  - Ad monetisation reuses OpenRTB and VAST (§8).

### Validation datasets

1. **Cookie Cats A/B test** [3].
   - Content: 90,189 players randomised to gate_30 or gate_40, with sum_gamerounds, retention_1, retention_7. Published as a DataCamp teaching dataset; licence unclear, verify.
   - *Computes:* D1/D7 retention by variant, engagement distribution, significance and bootstrap testing. A public analysis finds D1 not significant (p = 0.0755) and D7 significant (p = 0.0016).
2. **World of Warcraft Avatar History (WoWAH)** [4].
   - Content: 91,065 avatars, 667,032 sessions, Jan 2006–Jan 2009 (1,107 days), online players sampled every 10 minutes with level, race, class, zone and guild. Academic dataset; verify terms.
   - *Computes:* DAU/MAU, session length, inactivity churn, progression speed, guild effects.
3. **No public purchase-level (IAP) dataset was found.** Monetisation KPIs cannot be validated on open data (§16).

### What generic analytics gets wrong here

- It averages retention or ARPDAU across cohorts and days instead of pooling users, and mixes classic with rolling retention.
- It trends benchmark medians across report years whose samples differ (session length 5–6 min in the 2024 data vs 3.1–3.5 min in 2025) as if the market changed [1][2].
- It uses mean ARPPU/LTV on whale-dominated revenue, and ignores store fees and refunds.
- It reads a DAU fall as lost engagement when paid installs were paused — a cohort-mix effect.
- It judges A/B tests on D1 only; Cookie Cats shows a D7 effect with no significant D1 effect [3].

### Sources

- [1] GameAnalytics, 2025 Mobile Gaming Benchmarks (2024 data): https://www.gameanalytics.com/reports/2025-mobile-gaming-benchmarks
- [2] GameAnalytics, 2026 Mobile & PC Gaming Benchmarks (2025 data): https://www.gameanalytics.com/reports/2026-mobile-pc-gaming-benchmarks
- [3] Cookie Cats A/B dataset and analyses: https://github.com/K-Ashik/Mobile-Game-A-B-Testing · https://medium.com/@sysgear88/chi-square-test-with-cookie-cats-the-mobile-game-59e0580284f4
- [4] WoWAH: http://mmnet.iis.sinica.edu.tw/dl/wowah/ · ACM MMSys 2011 paper: https://dl.acm.org/doi/10.1145/1943552.1943569 · Kaggle mirror: https://www.kaggle.com/datasets/mylesoneill/warcraft-avatar-history

---

## 8. Advertising / adtech / performance marketing

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Viewability rate** | Viewable ÷ measured impressions. MRC thresholds [1][2]: display ≥50% of pixels for ≥1 continuous second; large display (≥242,500 px) ≥30% for ≥1 s; video ≥50% for ≥2 continuous seconds | Impression | Thresholds are the standard [1] | Dividing by *served* instead of *measured*. Blending vendors with different coverage. |
| **IVT rate** (GIVT/SIVT) | Invalid ÷ gross impressions or clicks [3][4]. **GIVT**: routine, list-based filtration (known bots and spiders, non-browser user agents, pre-fetch). **SIVT**: advanced analytics and human review (hijacked devices, adware, malware, misappropriated content) | Impression / click | Accredited measurers must apply GIVT; SIVT is strongly encouraged [3] | Reporting pre-filtration volumes. Billing on gross. |
| **CTR · CPC · CVR · CPA/CPL** (search) | Clicks ÷ impressions. Spend ÷ clicks. Conversions ÷ clicks. Spend ÷ conversions | Ad × day | WordStream/LocaliQ, all industries: average CTR 6.66% and CVR 7.52% (2025 report); average CPC $5.42 (2026 report). Pages blocked to fetch, as summarised [5][6]. Very vertical-dependent | Averaging CTRs or CPCs across campaigns. Mixed conversion definitions (lead vs sale). View-through conversions blended in. |
| **CPM · eCPM · RPM** | Spend (or publisher revenue) ÷ impressions × 1,000 | Impression | None verified | Mixing gross (advertiser-paid) and net (publisher-received) CPM. |
| **Working media ratio · unknown delta** | Share of advertiser spend reaching publishers. Unknown delta = spend that cannot be matched to any known cost | Spend line | ISBA/PwC 2020 (UK): publishers received about half of spend; unknown delta 15% (~⅓ of supply-chain costs); impression match rate 12% [7]. 2022 follow-up: unknown delta 3%, match rate 58%, publisher share up 8 pts [8] | Treating DSP-reported spend as media cost. |
| **Quality-adjusted spend (TrueAdSpend) · MFA share** | Share of programmatic spend buying benchmark-qualified impressions. Made-for-advertising inventory share | Campaign / period | ANA: Q1 2025 41% (36% in the 2023 study); MFA median 0.8% (Q2 2025) and 0.4% (Q3 2025); 56.7% for disciplined advertisers in Q4 2025; $26.8B estimated waste (Q2 2025) [9][10]. Participants only — selection bias | Benchmarking against a self-selected panel as if industry-wide. |
| **Fill rate · bid rate · win rate** | Filled ad requests ÷ requests. Bids ÷ bid requests. Wins ÷ bids | Ad request / bid request | None verified | Duplicate requests across SSPs inflate the denominator. Timeouts excluded silently. |
| **ROAS vs incremental ROAS (lift)** | Attributed revenue ÷ spend, vs (test − control) revenue ÷ spend | Campaign | None verified. IAB/MRC endorse RCTs, matched markets, counterfactual models and MMM for incrementality [11] | Last-touch attribution presented as incrementality. Platform-attributed conversions summed across channels (>100%). |
| **Reach · frequency** | Unique people (or devices) reached. Impressions ÷ reach | User × campaign | None | Device or cookie reach presented as people. |

### Playbook

1. **CPA rises.** Split into CPM × 1/CTR × 1/CVR (or CPC × 1/CVR), then check in order:
   1. Auction pressure (CPC/CPM) by keyword or placement.
   2. CTR by creative — fatigue.
   3. CVR by landing page, site release, broken tags.
   4. Audience, geo and device mix.
   5. Conversion-tracking and consent changes.
   6. Seasonality.

   *Action:* bid and budget moves, creative refresh, fix tracking, landing-page tests.
2. **Publisher ad revenue falls.** Split into requests × fill × eCPM, then check in order:
   1. Traffic and ad requests.
   2. Fill by demand partner.
   3. eCPM by format and geo.
   4. Viewability — buyers price low-viewability placements down [1].
   5. IVT filtration [3].
   6. ads.txt / sellers.json errors cutting off demand [14].

   *Action:* layout changes, fix ads.txt, set floors, direct deals.
3. **Viewability falls.** Check in order:
   1. Placement and format.
   2. Lazy-load and layout changes.
   3. App vs web mix.
   4. Measurement coverage (measured rate) [1].

   *Action:* prune placements, tune lazy-load thresholds.
4. **IVT rises.** Check in order:
   1. Paid traffic-acquisition sources.
   2. Specific sellers and supply paths (schain/sellers.json) [13][14].
   3. Data-centre IPs and geos.
   4. App bundles.

   *Action:* block paths, claw back spend.
5. **Attributed ROAS rises but a lift test is null.** Check in order:
   1. Retargeting of existing customers.
   2. Long attribution windows.
   3. Brand-search cannibalisation.

   *Action:* allocate budget on incrementality, not attribution [11].

### Ontology sketch

**Objects (22).** Advertiser · Agency · Brand · Campaign · Line Item/Ad Group/Insertion Order · Creative · Audience Segment · Targeting (keyword, context) · Publisher · Site/App · Placement/Ad Unit · Ad Request · Bid Request · Bid · Auction · Impression · Click · Conversion Event · Attribution Touch · Deal (PMP/PG) · Supply-Chain Node (SSP, exchange, reseller) · Verification Record (viewability/IVT) · Invoice/Reconciliation.

**Links**
- Advertiser 1:N Campaign 1:N Line Item. Line Item N:M Creative.
- Publisher 1:N Site 1:N Placement.
- Ad Request N:1 Placement. Ad Request 1:N Bid Request 1:N Bid.
- Auction 1:N Bid. Auction 0..1 winning Bid → 0..1 Impression.
- Impression N:1 Creative. Impression N:1 Line Item. Impression 1:N Click.
- Conversion N:M (Impression | Click) via Attribution Touch, carrying model and window.
- Bid Request 1:N ordered Supply-Chain Node (the schain) [13].
- Deal N:1 Publisher. Deal N:1 Buyer.

**Lifecycles**
- *Insertion order / campaign:* draft → approved → live ↔ paused → **completed** ∎. Or **cancelled** ∎. Then reconciled → invoiced → **paid** ∎.
- *Impression:* ad request → bid request → bid → won → served → measured → viewable → [clicked] → [converted]. **Filtered as IVT** ∎ is terminal before billing [3].
- *Creative:* uploaded → in review → **rejected** ∎ or approved → active → **archived** ∎.

**Processes & promises**
- Make-goods for under-delivery.
- IVT credits and clawbacks.
- First- vs third-party count reconciliation before billing.
- Attribution-window policy.
- Auction timeout (OpenRTB `tmax`) [12].

### Systems & standards

- **Systems:**
  - Ad servers: Google Ad Manager, Campaign Manager 360.
  - DSPs: The Trade Desk, DV360, Amazon DSP.
  - SSPs: Magnite, PubMatic, Index Exchange.
  - Search/social platforms: Google Ads, Meta, Microsoft Ads.
  - Verification: IAS, DoubleVerify.
  - MMPs, clean rooms, MMM tooling.
- **Standards:**
  - **OpenRTB 2.6** and the **SupplyChain object** (`source.schain`) [12][13].
  - **ads.txt / app-ads.txt / sellers.json** and IAB Tech Lab taxonomies [14].
  - **VAST 4.3** [15].
  - **MRC viewability** [1] and **IVT** guidelines [3][4].
  - **IAB/MRC Retail Media Measurement Guidelines** [11].

### Validation datasets

1. **Criteo Attribution Modeling for Bidding** [16].
   - Content: 16.5M impressions over 30 days, ~700 campaigns, ~45k conversions. Fields: timestamp, user, campaign, conversion (within 30 days) with timestamp and id, attribution flag, click, click position, click count, cost, cost-per-order, time since last click, 9 categorical features. 623 MB compressed.
   - Licence: CC BY-NC-SA 4.0.
   - *Computes:* CTR, CVR, conversion lag distributions, attributed vs unattributed conversion share, cost per order.
2. **iPinYou RTB dataset (2013)** [17].
   - Content: three seasons, about one week each, 35 GB total. Bid, impression (with paying price), click and conversion logs; seasons 2–3 share one schema.
   - *Computes:* win rate, paid CPM, CTR/CVR, bidding-strategy back-tests. Research use; verify terms.
3. **No public dataset with ground-truth incrementality or MMM was verified** (§16).

### What generic analytics gets wrong here

- It divides by served impressions where measured or viewable impressions are required, and blends vendors [1].
- It reports attributed conversions as incremental, and sums platform-attributed conversions across channels [11].
- It averages CTR, CPC and CPA across campaigns instead of pooling clicks, impressions and spend.
- It treats DSP spend as working media, ignoring supply-chain fees and the unknown delta [7][8].
- It leaves invalid traffic in denominators and in billing reconciliation [3].

### Sources

- [1] MRC Viewable Ad Impression Measurement Guidelines: https://www.iab.com/wp-content/uploads/2015/06/MRC-Viewable-Ad-Impression-Measurement-Guideline.pdf
- [2] Google Ads Help, Active View viewability: https://support.google.com/google-ads/answer/7029393?hl=en
- [3] IAB, MRC IVT Detection & Filtration Guidelines Addendum: https://www.iab.com/guidelines/mrc-invalid-traffic-ivt-detection-and-filtration-guidelines-addendum/
- [4] MRC IVT Addendum update (2020): https://mediaratingcouncil.org/sites/default/files/Standards/IVT%20Addendum%20Update%20062520.pdf
- [5] WordStream, 2025 Google Ads Benchmarks: https://www.wordstream.com/blog/2025-google-ads-benchmarks
- [6] WordStream, 2026 Google Ads Benchmarks: https://www.wordstream.com/blog/2026-google-ads-benchmarks
- [7] ISBA Programmatic Supply Chain Transparency Study (2020), executive summary: https://www.isba.org.uk/system/files/media/documents/2020-12/executive-summary-programmatic-supply-chain-transparency-study.pdf
- [8] ISBA/PwC Study II summary (Jan 2023): https://www.isba.org.uk/system/files/media/documents/2023-01/ISBA%20%20PwC%20programmatic%20supply%20chain%20study%20II%20(summary)-%2018%20January%202023.pdf
- [9] ANA Q2 2025 Programmatic Transparency Benchmark: https://www.ana.net/content/show/id/pr-2025-08-programmatictrans
- [10] ANA Q4 2025 benchmark: https://www.ana.net/content/show/id/pr-2026-02-programatic · Q1 2025 findings: https://s3.amazonaws.com/media.mediapost.com/uploads/ANAQ12025Programmatic.pdf · Q3 2025 findings: https://s3.amazonaws.com/media.mediapost.com/uploads/Q32025ProgrammaticTransparencyBenchmark.pdf
- [11] IAB/MRC Retail Media Measurement Guidelines: https://www.iab.com/wp-content/uploads/2024/01/IAB_Retail_Media_Measurement_Guidelines_January2024.pdf
- [12] OpenRTB 2.6: https://github.com/InteractiveAdvertisingBureau/openrtb2.x/blob/main/2.6.md
- [13] SupplyChain object: https://github.com/InteractiveAdvertisingBureau/openrtb/blob/main/supplychainobject.md
- [14] IAB Tech Lab, Supply Chain & Foundations (ads.txt, sellers.json, taxonomies): https://iabtechlab.com/standards/supply-chain-foundations/
- [15] IAB Tech Lab, VAST: https://iabtechlab.com/standards/vast/
- [16] Criteo AI Lab, Attribution Modeling for Bidding dataset: https://ailab.criteo.com/criteo-attribution-modeling-bidding-dataset/
- [17] Zhang et al., "Real-Time Bidding Benchmarking with iPinYou Dataset": https://arxiv.org/abs/1407.7073 · https://contest.ipinyou.com/

---

## 9. Mobility / ride-hailing / car rental

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Trips** | Uber: completed consumer Mobility rides and Delivery orders. An UberX Share ride with three paying consumers = **3 trips**; an UberX ride with three passengers = **1 trip** [1] | Completed trip per paying consumer | Uber Q2 2025: 3.268B trips (Mobility + Delivery) [1] | Counting requests or dispatches. Vehicle-trip vs payer-trip confusion on pooled rides. |
| **MAPCs · Active Riders** | Uber MAPCs: unique consumers with ≥1 completed ride or delivery in a month, averaged over the quarter's months [1]. Lyft Active Riders: unique riders with ≥1 ride in the **quarter** [2] | Consumer × month (Uber) / × quarter (Lyft) | Uber Q2 2025: 180M MAPCs [1] | Comparing a monthly-averaged count with a quarterly unique count. |
| **Gross Bookings** | Uber: total dollar value incl. taxes, tolls and fees of rides, delivery orders (and Freight); **excludes tips** [1]. Lyft: invoiced to riders incl. taxes, tolls, fees, excluding tips, plus other offerings [2] | Trip | Uber Q2 2025: $46.756B (Mobility $23.762B; Delivery $21.734B) [1] | Comparing tip-exclusive GB (Uber) with tip-inclusive GOV (DoorDash, §15). Scope differences (rentals, media in Lyft GB). |
| **Take rate · margin on GB** | Revenue ÷ GB. Adjusted EBITDA ÷ GB | Segment × period | Uber Q2 2025: Mobility ≈ 30.7%, Delivery ≈ 18.9% (computed); adjusted EBITDA 4.5% of GB [1] | Principal-vs-agent revenue recognition and incentive accounting move revenue without any economic change (cf. §4 Eternal). |
| **Driver utilisation** | Time with passenger ÷ total logged-in time, incl. driving to pickup and cruising [3] | Driver × hour | NYC TLC estimates for 2017: Uber and Lyft 58%, Juno 50%, Via 70% (Parrott & Reich 2018, as summarised) [3] | Denominator excludes en-route or idle time. Ignores drivers logged into several apps at once. |
| **Wait time · fulfilment rate** | Request → pickup minutes. Completed ÷ requested | Request | None verified. TLC HVFHV data carries request and pickup timestamps; on-scene time only for wheelchair-accessible trips [4] | Measuring wait on completed trips only. Unfulfilled and cancelled requests invisible. |
| **Driver pay share · earnings per hour** | Driver pay ÷ passenger fare. Driver pay ÷ engaged (or online) hours. TLC `driver_pay` excludes tolls and tips and is net of commission, surcharges, taxes [4] | Trip / driver-hour | Parrott & Reich: 16.6% industry-average commission (2017) [3] | Engaged vs online hours denominator. Tips in or out. |
| **Transaction Days** (car rental) | Total 24-hour periods vehicles were on rent; partial periods count as one, so a vehicle can earn >1 TD in 24 h [5] | Rental contract × day | Hertz FY2024: 153.9M TDs [6] | Calendar days ≠ transaction days. |
| **Vehicle utilisation** (car rental) | Transaction Days ÷ Available Car Days (average rentable vehicles × days). Rentable vehicles **exclude** vehicles held for sale [5] | Fleet × day | Hertz FY2024: 79% overall (Americas 80%, International 76%) [6] | Using the whole fleet, including vehicles being sold. |
| **Total RPD · depreciation per unit per month** | Rental revenue ÷ transaction days, FX-adjusted. Depreciation of revenue-earning vehicles and lease charges per average vehicle per month [5] | Period | Hertz FY2024: Total RPD $59.14 (2023: $61.09); revenue per unit per month $1,429; depreciation per unit per month $539 (2023: $309) [6] | Ignoring residual-value swings. Comparing RPD across rental lengths (long rentals price lower per day). |

### Playbook

1. **Ride-hail gross bookings fall.** Split into trips × average fare, then check in order:
   1. Request volume by zone and hour.
   2. Fulfilment rate (supply shortfall, cancellations).
   3. Price and surge levels.
   4. Product mix (shared, premium).
   5. Airports and events calendar.
   6. Competitor promotions.

   *Action:* zone-targeted driver incentives, rider promotions, pricing.
2. **Wait times rise or fulfilment falls.** Check in order:
   1. Online driver hours.
   2. Utilisation — too high means no idle supply [3].
   3. Geographic imbalance.
   4. Driver cancellations of short or low-fare trips.
   5. Weather and events.

   *Action:* driver quests, dispatch radius, pricing.
3. **Take rate falls.** Check in order:
   1. Driver incentives.
   2. Rider promotions.
   3. Insurance cost.
   4. Regulatory pay floors [7].
   5. Product mix.
   6. Principal/agent accounting changes.

   *Action:* incentive efficiency review, pricing.
4. **Car-rental margin falls.** Check in order:
   1. RPD: pricing, leisure vs corporate vs replacement mix, rental length.
   2. Utilisation: fleet sizing, vehicles in repair.
   3. Depreciation per unit: residual values, fleet mix, hold period [6].
   4. Damage and maintenance cost per transaction day.

   *Action:* defleet or rotation timing, pricing, repair throughput.
5. **Driver churn rises.** Check in order:
   1. Earnings per hour (= utilisation × fare × pay share).
   2. Incentive changes.
   3. Deactivations.
   4. Fuel cost.

   *Action:* incentive redesign, supply scheduling.

### Ontology sketch

**Objects (22).**
- *Ride-hail:* Rider/Consumer · Driver (earner) · Vehicle · Driver Session (online period) · Ride Request · Dispatch Offer · Trip · Pooled Leg · Fare Quote (incl. surge) · Payment · Tip · Driver Payout · Incentive/Promotion · Zone · Rating · Support/Safety Ticket.
- *Car rental:* Rental Location · Reservation · Rental Agreement (contract) · Fleet Unit (VIN) · Vehicle Class · Damage Claim · Maintenance Order · Disposal Sale.

**Links**
- Rider 1:N Request. Request 1:N Dispatch Offer N:1 Driver.
- Request 1:0..1 Trip. Trip N:1 Driver. Trip N:1 Vehicle.
- Pooled Trip 1:N Leg (one per paying rider).
- Trip 1:1 Fare. Trip 1:N Payment. Trip 0..1 Tip.
- Driver 1:N Session. Payout N:M Trip.
- Trip N:1 pickup Zone. Trip N:1 drop-off Zone.
- Reservation N:1 pickup Location. Reservation N:1 return Location (one-way rentals).
- Reservation 1:0..1 Agreement. Agreement 1:N Fleet Unit (vehicle swaps).
- Fleet Unit 1:N Maintenance Order. Agreement 1:N Damage Claim. Fleet Unit 1:0..1 Disposal Sale.

**Lifecycles**
- *Ride request:* requested → matched → driver en route → arrived → on trip → **completed** ∎. Or **cancelled by rider** ∎, **unfulfilled** ∎. A driver cancellation returns the request to dispatch.
- *Driver:* applied → screened → onboarded → active ↔ inactive → **deactivated** ∎ / **churned** ∎.
- *Rental:* booked → confirmed → picked up (agreement opened) → on rent [extended]* → returned (agreement closed) → **invoiced** ∎. Or **cancelled** ∎ / **no-show** ∎.
- *Fleet unit:* ordered → in fleet → rentable ↔ in repair → held for sale (excluded from rentable fleet [5]) → **sold** ∎.

**Processes & promises**
- Quoted pickup ETA and upfront fare.
- Driver pay floors where regulated [7].
- Wheelchair-accessible service obligations [4].
- Vehicle ready at the rental pickup time.
- Return grace periods.
- Damage-claim handling.

### Systems & standards

- **Systems:**
  - In-house dispatch/marketplace platforms.
  - Payments processors.
  - Telematics.
  - Background-check vendors.
  - Regulator trip reporting (NYC TLC) [8].
  - Car-rental counter and fleet systems.
  - GDS/OTA car distribution.
  - Repair and remarketing vendors.
- **Standards:**
  - **MDS** (Open Mobility Foundation) for agency–operator data.
  - **GBFS** (MobilityData) public feeds for shared bikes, scooters and car share [9][10].
  - **OpenTravel** vehicle availability/reservation messages (§1 [10]).
  - Company definitions from Uber, Lyft and Hertz filings [1][2][5].

### Validation datasets

1. **NYC TLC High Volume FHV trip records** [4][8].
   - Content: one row per trip by Uber (HV0003), Lyft (HV0005), Via (HV0004), Juno (HV0002), since Feb 2019. Monthly Parquet files with about a two-month lag; TLC does not guarantee accuracy.
   - Fields: request / on-scene / pickup / drop-off times, zones, trip_miles, trip_time, base_passenger_fare, tolls, surcharges, tips, driver_pay, shared request/match flags, WAV flags, cbd_congestion_fee (from 5 Jan 2025).
   - *Computes:* trips by zone and hour, request→pickup wait, fare per mile, driver-pay share of fare, tip rate, shared-ride match rate, airport share, operator share.
   - *Cannot compute:* online hours (so not utilisation), cancelled or unfulfilled requests.
2. **NYC yellow/green taxi records** (since 2009 / 2013) [8].
   - *Computes:* taxi vs app-based benchmarks, payment mix.
3. **GBFS public feeds** [10].
   - *Computes:* micromobility availability and utilisation proxies from status snapshots.

No public car-rental transaction-day data was found (§16).

### What generic analytics gets wrong here

- It compares gross bookings across companies with different tip, tax and scope treatment: Uber excludes tips, DoorDash GOV includes them [1] (§15).
- It counts vehicle trips or requests instead of completed trips per paying consumer [1].
- It measures wait time on completed trips only, so unfulfilled requests disappear.
- It builds utilisation on the wrong denominator: excluding en-route and idle time, or counting held-for-sale rental cars [3][5].
- It reads take-rate moves as pricing when incentives, accounting or business model changed.

### Sources

- [1] Uber Q2 2025 earnings release (definitions and figures): https://www.sec.gov/Archives/edgar/data/1543151/000154315125000020/uberq225earningspressrelea.htm · Uber 10-K FY2025: https://www.sec.gov/Archives/edgar/data/1543151/000154315126000015/uber-20251231.htm
- [2] Lyft 10-K FY2023: https://www.sec.gov/Archives/edgar/data/1759509/000175950924000019/lyft-20231231.htm · Lyft Q2 2025 release: https://www.sec.gov/Archives/edgar/data/1759509/000175950925000123/lyft-20250630xpressrelease.htm
- [3] Parrott & Reich, *An Earnings Standard for New York City's App-based Drivers* (July 2018): https://static1.squarespace.com/static/53ee4f0be4b015b9c3690d84/t/5b3a3aaa0e2e72ca74079142/1530542764109/Parrott-Reich+NYC+App+Drivers+TLC+Jul+2018jul1.pdf · Streetsblog summary: https://nyc.streetsblog.org/2018/07/09/how-higher-wages-for-uber-drivers-could-cut-traffic-on-nyc-streets
- [4] NYC TLC, HVFHV data dictionary (18 Mar 2025): https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_hvfhs.pdf
- [5] Hertz 10-K FY2022 (Transaction Days, Utilization, RPD, depreciation definitions): https://www.sec.gov/Archives/edgar/data/1657853/000165785323000039/htz-20221231.htm
- [6] Hertz Q4 & FY2024 results: https://www.sec.gov/Archives/edgar/data/1657853/000165785325000011/q42024earningsrelease.htm
- [7] NYC TLC, proposed amendment of HVFHS driver pay rules: https://www.nyc.gov/assets/tlc/downloads/pdf/proposed_amendment_of_driver_pay_rules_for_hvfhs.pdf
- [8] NYC TLC Trip Record Data: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- [9] Open Mobility Foundation, MDS: https://github.com/openmobilityfoundation/mobility-data-specification
- [10] OMF, "Understanding the relationship between GBFS and MDS": https://www.openmobilityfoundation.org/understanding-gbfs-and-mds/

---

## 10. Real estate / property management

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **NOI** | Property revenue − operating expenses (before debt service, capex, depreciation) [1] | Property × period (TTM or forward 12 months) | — | Including capex or debt service. Straight-line vs cash rent mixed. One-offs left in. |
| **Cap rate** | Stabilised NOI ÷ acquisition price. Value-add: stabilised NOI after enhancements ÷ (price + value-add capital) [1] | Asset / market × sector × class | CBRE H2 2025, US Class A stabilised [1]: **multifamily infill** mostly 4.25–6.5% (Austin/Dallas 4.25–4.75%, Pittsburgh 5.5–6.5%); **industrial** 4.75–7% (NYC/N. New Jersey 4.75–5.25%, Oklahoma City/Tulsa 6.5–7%); **neighbourhood retail** 4.5–7.75% (NYC 4.5–5.5%, Albuquerque 7–7.75%); **downtown office** 5.5–14% (NYC 5.5–6%, Pittsburgh 11–14%); **suburban office** 6–12.75%; **hotels** from 5–6.5% (NYC luxury resort) to 8.5–11% (Detroit limited-service). *Drivers:* sector, market, class, stabilisation, interest rates | Averaging cap rates unweighted. Comparing trailing-NOI transaction cap rates with forward, stabilised survey estimates. |
| **Occupancy** (physical vs economic) | Occupied units or SF ÷ total. Economic = collected (or billed) rent ÷ gross potential rent | Property × month | NCREIF NPI only includes operating properties ≥60% leased [2] | Leased vs occupied. Concessions and bad debt hidden inside physical occupancy. Down units excluded from the denominator. |
| **Renewal (retention) rate** | Renewed leases ÷ expiring leases, per expiration cohort | Lease-expiration cohort | RealPage, US market-rate apartments: >57% renewed over the 12 months to late 2025 (+3.5 pts YoY); 54.5% at end-2024; 2010–2019 average 50.7% (as summarised) [3] | Denominators that include transfers, early terminations or month-to-month leases. |
| **Turn time · turn cost** | Move-out → move-in days (split make-ready vs marketing days). Cost per turn | Unit turn | None verified | Measuring only completed turns. |
| **Delinquency · bad debt** | Past-due rent ÷ billed rent. Write-offs ÷ gross potential rent | Property × month | None verified | Payment plans and prepayments netted. |
| **Lease trade-out · rent growth** | New lease rent ÷ prior lease rent − 1, split new vs renewal. Effective = net of concessions | Lease | None verified | Asking vs effective rent confusion. |
| **Unlevered total return** (income + appreciation) | NCREIF NPI: quarterly unleveraged composite total return on private CRE held for investment, market-value accounting [2] | Property × quarter | Index series [2] | Levered vs unlevered mixing. Treating appraisal-based returns as transaction prices (smoothing and lag). |
| **FFO** (REITs) | GAAP net income excluding gains/losses on property sales, impairments of depreciable real estate, and real-estate depreciation & amortisation [4] | Company × quarter | Nareit 2018 restatement [4] | Treating AFFO or "core FFO" as standardised — they are company-defined. |
| **Months' supply · days on market · median price** (brokerage) | Months' supply = inventory ÷ monthly sales pace [5]. DOM = listing to contract | Market × month | NAR May 2025: 1.54M homes for sale = 4.6 months at 4.03M SAAR; median existing-home price $422,800 [5]. Median DOM 41 days (Mar 2026) [6] | Mixing seasonally adjusted annual rates with raw monthly counts. Median of regional medians. Listing date vs close date. |

### Playbook

1. **NOI falls.**
   - *Revenue side, check in order:* economic vs physical occupancy → trade-out and renewal pricing → concessions → bad debt → other income.
   - *Expense side:* controllable (payroll, repairs & maintenance, turns) vs non-controllable (tax, insurance, utilities).

   *Action:* pricing and renewal strategy, collections, vendor re-bids, tax appeals.
2. **Occupancy falls.** Split into move-outs vs move-ins vs unrentable units. Check in order:
   1. Renewal rate by move-out reason [3].
   2. Lead → tour → application → approval conversion.
   3. Make-ready days (units not rentable).
   4. New supply in the submarket.
   5. Price vs comparables.

   *Action:* renewal offers, marketing, turn-crew capacity, pricing.
3. **Delinquency rises.** Check in order:
   1. Move-in cohort (screening quality).
   2. Payment-method changes.
   3. Local employment shocks.
   4. Eviction timelines.
   5. Application fraud.

   *Action:* screening rules, payment plans, legal process.
4. **Asset value (cap-rate implied) falls.** Separate NOI decline from market cap-rate expansion (rates, sector sentiment — office spreads are widest [1]).

   *Action:* hold/sell, refinance timing.
5. **Maintenance cost rises.** Check in order:
   1. Work orders per unit.
   2. Repeat work orders (first-time-fix failures).
   3. Emergency share.
   4. Vendor rates.
   5. Asset age.

   *Action:* preventive maintenance, repair-vs-replace capex.
6. **(Brokerage) Days on market rise.** Check in order:
   1. Months' supply.
   2. Price reductions.
   3. Mortgage rates.
   4. Seasonality [5].

   *Action:* pricing guidance to sellers.

### Ontology sketch

**Objects (23).** Fund/Portfolio · Asset (property) · Building · Floor · Unit/Space · Area Measurement · Lease · Lease Term/Clause (rent steps, options) · Party (tenant, resident, guarantor) · Lead/Prospect · Tour · Application · Charge (rent ledger) · Payment · Concession · Work Order · Vendor · Inspection · Capex Project · Budget · Valuation/Appraisal · Loan · MLS Listing · Sale Transaction.

**Links**
- Fund 1:N Asset 1:N Building 1:N Unit.
- Lease N:1 Unit — commercial leases can be N:M Space.
- Lease N:M Party.
- Lease 1:N Charge. Charge N:M Payment (allocations).
- Lead 1:N Tour. Lead 0..1 Application 0..1 Lease.
- Work Order N:1 Unit. Work Order N:0..1 Vendor.
- Asset 1:N Valuation. Asset N:M Loan.
- Listing N:1 Property. Sale N:1 Property.

**Lifecycles**
- *Residential unit:* occupied → on notice → vacant-unready (make-ready) → vacant-ready → pre-leased → occupied. Down/offline is a side state.
- *Lease:* draft → executed → commenced (move-in) → active → [renewed = new term] → notice → **expired/moved out** ∎. Or **terminated early** ∎ / **evicted** ∎. Month-to-month holdover is a side state.
- *Application:* submitted → screening → approved → **lease signed** ∎. Or **denied** ∎ / **withdrawn** ∎.
- *Work order:* opened → assigned → in progress → completed → **closed (verified)** ∎. Or **cancelled** ∎.
- *MLS listing:* coming soon → active → pending → **closed** ∎. Or **withdrawn / expired / cancelled** ∎. Use RESO standard status names [7].

**Processes & promises**
- Emergency work-order response.
- Deposit return deadlines (jurisdictional).
- Notice periods.
- Rent due and late-fee schedule.
- Renewal offer lead time.
- Commercial CAM reconciliation.

### Systems & standards

- **Systems:**
  - Property management: Yardi Voyager, RealPage, Entrata, AppFolio, MRI.
  - Leasing CRM.
  - Maintenance CMMS.
  - Investment modelling and valuation: Argus.
  - Fund accounting.
  - MLS systems via RESO Web API.
- **Standards:**
  - **RESO Data Dictionary**: listing/property/member vocabulary across 700+ MLSs [7].
  - **OSCRE Industry Data Model**: asset lifecycle definitions across 150+ use cases [8].
  - **IPMS**: International Property Measurement Standards [9].
  - **NCREIF NPI** [2] and **Nareit FFO** [4] for return and earnings definitions.

### Validation datasets

1. **HM Land Registry Price Paid Data** (England & Wales) [10].
   - Content: all residential sales since 1 Jan 1995, monthly updates, complete CSV ~5.3 GB.
   - Licence: OGL v3; address fields carry OS/Royal Mail third-party rights.
   - *Computes:* transaction volume, median price and growth by area, property type, new-build share, tenure.
   - *Cannot compute:* rents, NOI, occupancy.
2. **NYC Rolling & Annualized Sales** (NYC Department of Finance) [11].
   - Content: 12-month rolling plus annual files since 2003, with borough, neighbourhood, building class, sale price, gross SF, year built.
   - *Computes:* $/SF by class and neighbourhood, volume. Non-arm's-length $0 transfers must be filtered.
3. **Inside Airbnb** (§1).
   - *Computes:* short-term-rental supply and pricing pressure on residential stock.
4. **Redfin Data Center** [12].
   - Content: downloadable market tracker, price drops, delistings, home price index. Terms not stated on the page; verify.

**No public rent-roll, lease or work-order dataset was found.** Renewal, delinquency and turn KPIs cannot be validated on open data (§16).

### What generic analytics gets wrong here

- It averages cap rates unweighted, or compares trailing transaction cap rates with forward, stabilised survey ranges [1].
- It reads physical occupancy as revenue health while concessions and bad debt erode economic occupancy.
- It computes renewal rates with inconsistent denominators (transfers, early terminations, month-to-month).
- It treats appraisal-based index returns (NPI) as market prices, ignoring smoothing and lag [2].
- It includes $0 and non-arm's-length transfers in sale-price medians from deed records.

### Sources

- [1] CBRE, U.S. Cap Rate Survey H2 2025 (definitions p.7; sector tables pp.9–21): https://www.cbre.com/insights/reports/us-cap-rate-survey-h2-2025 · PDF: https://mediaassets.cbre.com/-/media/project/cbre/shared-site/teams/united-states/ft-lauderdale/calum-weaver/cbre-us-cap-rate-survey-h2-2025.pdf
- [2] NCREIF Property Index (NPI): https://user.ncreif.org/data-products/property/
- [3] RealPage Analytics, "What We Got Right and Wrong in 2025": https://www.realpage.com/analytics/what-we-got-right-2025/ · "Retention Rates Climb Amid Supply Wave": https://www.realpage.com/analytics/retention-climbs-october-2024/
- [4] Nareit FFO White Paper, 2018 restatement: https://www.reit.com/sites/default/files/2018-FFO-white-paper-(11-27-18).pdf
- [5] NAR, Existing-Home Sales, May 2025: https://s24.q4cdn.com/538403808/files/doc_news/NAR-Existing-Home-Sales-Report-Shows-0-8-Increase-in-May-2025.pdf · "Existing-Home Sales Explained": https://www.nar.realtor/research-and-statistics/housing-statistics/existing-home-sales/existing-home-sales-explained
- [6] NAR, March 2026 existing-home sales: https://www.nar.realtor/newsroom/nar-existing-home-sales-report-shows-3-6-decrease-in-march
- [7] RESO Data Dictionary: https://www.reso.org/data-dictionary/
- [8] OSCRE: https://www.oscre.org/
- [9] IPMS Coalition: https://ipmsc.org/
- [10] HM Land Registry, Price Paid Data: https://www.gov.uk/guidance/about-the-price-paid-data · single file: https://www.gov.uk/government/statistical-data-sets/price-paid-data-single-file
- [11] NYC Department of Finance, Rolling Sales: https://www.nyc.gov/site/finance/property/property-rolling-sales-data.page
- [12] Redfin Data Center: https://www.redfin.com/news/data-center/

---

## 11. Education / edtech (higher education and online learning)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **First-year retention rate** | NCES/IPEDS: % of first-time, full-time, degree-seeking undergraduates who return to the **same institution** the following fall [1] | Entering fall cohort | Fall 2017 cohort, 4-year institutions: 81% overall (public 81%, private nonprofit 81%, for-profit 60%). Open-admission publics 63% vs institutions accepting <25% at 97%. 2-year institutions: 62% [1]. *Driver:* selectivity | Including part-time or transfer-in students. Mixing retention (same institution) with persistence (any institution). |
| **Persistence rate** | NSC: % of an entering cohort enrolled at **any** institution the second fall [2] | Entering cohort | Fall 2023 cohort, all students and sectors: persistence 77.6%, retention 69.5% [2] | Comparing NSC figures (all students, any institution) with IPEDS figures (full-time first-time, same institution). |
| **Graduation rate** (150% of normal time) | Completers within 150% of normal time at the starting institution ÷ adjusted cohort. Transfer-outs without a degree count as **non-completers** [1] | Entering cohort | Fall 2012 bachelor's cohort: 62% within 6 years (public 61%, private nonprofit 67%, for-profit 25%; open admissions 34% vs <25% acceptance 90%). 2-year fall 2015 cohort: 33% within 150% [1] | Cross-sectional graduates ÷ enrolment instead of a cohort measure. Treating transfer-outs as failures in narratives. |
| **Acceptance rate · yield** | Admits ÷ completed applications. Enrolled ÷ admitted. IPEDS Admissions collects yields [3] | Application cycle | Institution-specific | Counting deposits as enrolled (summer melt). Incomplete applications in the denominator. |
| **Course success · DFW rate** | Enrolments with D, F or W ÷ enrolments at census | Section × term | None verified | Averaging section rates instead of pooling enrolments. Inconsistent treatment of pre-census drops. |
| **Online course completion** | Completers ÷ starters, split by learner intent (auditing vs paid/verified) | Course run | edX (HarvardX/MITx, 565 courses, 2012–May 2018): completion rates low and not improving over six years [4][5] | All registrants as denominator. Free and paid learners pooled. |
| **DAU · MAU · paid subscribers** (consumer edtech) | Duolingo: DAU = unique users engaging with the app or learning section each calendar day, averaged over the period; MAU = average of each calendar month's MAU [6] | User × day | Company-defined [6] | Rolling 30-day vs calendar month. Paid conversion ÷ MAU vs ÷ DAU. |
| **Mastery · assessment performance** | Correct response rate. Knowledge-tracing mastery estimates. Assessment pass rate | Learner × item attempt | Dataset-derived [7][8] | Item exposure bias: adaptive systems show harder items to stronger learners. |
| **Early engagement → outcome** | LMS/VLE activity in the first weeks vs final result | Learner × module | Dataset-derived (OULAD) [8] | Clicks treated as learning. Missing-data students assumed disengaged. |

### Playbook

1. **First-year retention falls.** Check in order:
   1. Academic preparation of the entering cohort.
   2. First-term credits attempted vs earned, and DFW in gateway courses.
   3. Unmet financial need and registration holds.
   4. Early LMS engagement [8].
   5. Part-time and working status.
   6. Commuter vs residential.

   *Action:* early-alert advising, gateway-course redesign, emergency aid, hold removal.
2. **Yield falls.** Check in order:
   1. Admit mix (out-of-state, international).
   2. Net price vs competitors.
   3. Aid-offer timing.
   4. Campus-visit rate.
   5. Deposit-deadline changes.

   *Action:* aid leveraging, targeted outreach.
3. **Graduation rate falls.** Check in order:
   1. Credit accumulation per term.
   2. Major changes and excess credits.
   3. Course-availability bottlenecks.
   4. Rising transfer-outs (non-completers by rule [1]).
   5. Financial stop-outs.

   *Action:* degree maps, section scheduling, completion grants.
4. **Online completion falls.** Check in order:
   1. Learner-intent mix (free vs paid) [4].
   2. Week-1 activity drop.
   3. Module-level drop-off spikes (difficulty, video length).
   4. Pacing and deadline changes.

   *Action:* onboarding, module redesign, nudges.
5. **Edtech DAU or paid conversion falls.** Check in order:
   1. New-user cohort mix (paid acquisition).
   2. Streak and notification changes.
   3. App releases.
   4. Pricing and trial changes.
   5. School-calendar seasonality.

   *Action:* roll back, pricing tests.

### Ontology sketch

**Objects (22).** Institution/Campus · Program (CIP-coded) · Course · Section (course offering in a term) · Term · Instructor · Student/Learner · Applicant · Application · Admission Decision · Term Registration · Enrolment (student × section) · Grade · Credential/Degree Award · Financial Aid Award · Tuition Charge/Payment · Advising Note · Learning Activity (LMS event) · Assessment · Item Response · Competency (standard) · Entering Cohort · (edtech) Subscription.

**Links**
- Institution 1:N Program. Program N:M Course.
- Course 1:N Section N:1 Term. Section N:M Instructor.
- Student 1:N Term Registration 1:N Enrolment N:1 Section. Enrolment 1:0..1 Grade.
- Student N:M Program (major changes over time).
- Student 1:N Aid Award. Student 1:N Credential N:1 Program.
- Applicant 1:N Application N:1 (Program × Term). Application 1:0..1 Decision.
- Section 1:N Assessment 1:N Item Response N:1 Student.
- Learning Activity N:1 Student. Learning Activity N:1 Section or resource.
- Item N:M Competency.
- Student N:1 Entering Cohort (fixed at entry, never re-assigned).

**Lifecycles**
- *Applicant:* inquiry → applied → complete → admitted / waitlisted / **denied** ∎ → deposited → **enrolled at census** ∎. Or **melted** ∎ / **declined** ∎.
- *Student status:* enrolled → continuing → stopped out → re-enrolled. Terminal: **graduated** ∎, **transferred out** ∎, **withdrawn** ∎, **dismissed** ∎.
- *Section enrolment:* registered → enrolled at census → **graded** ∎. Or **withdrew (W)** ∎; incomplete (I) → graded ∎. Pre-census drops are not enrolments.
- *Online learner:* registered → started → active → **completed / certified** ∎. Or **inactive** ∎; upgrade to paid/verified is a transition.

**Processes & promises**
- Census-date enrolment snapshot.
- IPEDS survey components: Fall Enrollment, Graduation Rates, Admissions [1][3].
- Aid disbursement dates.
- Grade submission deadlines.
- Accommodation requests.
- Certificate issuance on completion.

### Systems & standards

- **Systems:**
  - SIS: Ellucian Banner/Colleague, Workday Student, PeopleSoft Campus Solutions.
  - LMS: Canvas, Blackboard, Moodle, D2L Brightspace.
  - Admissions CRM: Slate, Salesforce Education Cloud.
  - Financial-aid and degree-audit systems.
  - MOOC and consumer-learning platforms.
- **Standards:**
  - **1EdTech**: LTI (tool launch), OneRoster (rosters and grades), Caliper Analytics (learning-activity events), CASE (competencies), CLR (comprehensive learner record) [9].
  - **CEDS** (Common Education Data Standards, NCES): a common vocabulary of 2,000+ education data elements (as summarised) [10].
  - **IPEDS** survey definitions [1][3].
  - **College Scorecard** data dictionary [11].

### Validation datasets

1. **OULAD — Open University Learning Analytics Dataset** [8].
   - Content: 32,593 students across 22 presentations of 7 modules, 2013–2014, with demographics, registration and un-registration dates, assessment scores and submission dates, 10M+ rows of daily VLE clicks, and final result.
   - Licence: CC BY 4.0.
   - *Computes:* withdrawal and pass rates, early-engagement → outcome curves, late-submission effects, assessment performance by cohort.
2. **College Scorecard** (US Department of Education) [11].
   - Content: institution-level files 1996-97 → 2025-26, plus field-of-study files: completion, retention, earnings, debt, repayment. Public data.
   - *Computes:* retention and completion by institution, net price, earnings by program (CIP).
3. **EdNet** [7].
   - Content: 784,309 students, 131.4M interactions, 13,169 questions; four levels KT1–KT4, where **KT4 includes purchase and coupon actions**.
   - Licence: CC BY-NC 4.0.
   - *Computes:* knowledge tracing, time on task, engagement churn, freemium purchase funnel.

### What generic analytics gets wrong here

- It mixes retention (same institution, IPEDS full-time first-time) with persistence (any institution, NSC all students) [1][2].
- It computes graduation rate cross-sectionally (graduates ÷ enrolment) instead of as a cohort measure within 150% time, and forgets that transfer-outs are non-completers by rule [1].
- It uses all MOOC registrants as the completion denominator, or pools free and paid learners [4].
- It counts deposits as enrolled students (summer melt), and headcount as FTE.
- It averages course pass rates across sections instead of pooling enrolments.

### Sources

- [1] NCES, *The Condition of Education 2020*, "Undergraduate Retention and Graduation Rates": https://nces.ed.gov/programs/coe/pdf/coe_ctr.pdf
- [2] NSC Research Center, Persistence & Retention 2025 (methodology notes): https://nscresearchcenter.org/wp-content/uploads/PersistenceandRetention2025_MethodNotes.pdf · Forbes summary: https://www.forbes.com/sites/michaeltnietzel/2025/06/26/college-student-persistence-rate-improves-again-hits-nine-year-high/ · Inside Higher Ed: https://www.insidehighered.com/news/student-success/academic-life/2025/06/26/first-year-persistence-continues-slow-climb-pandemic
- [3] IPEDS survey components (Admissions): https://nces.ed.gov/ipeds/survey-components/9
- [4] Reich & Ruipérez-Valiente, "The MOOC pivot," *Science* 363 (2019): https://www.science.org/doi/10.1126/science.aav7958 · MIT TSL: https://tsl.mit.edu/research/the-mooc-pivot/
- [5] MOOC_Pivot repository (565 courses, 2012–May 2018): https://github.com/jruiperezv/MOOC_Pivot
- [6] Duolingo 10-K FY2024: https://www.sec.gov/Archives/edgar/data/1562088/000156208825000042/duol-20241231.htm
- [7] EdNet: https://github.com/riiid/ednet
- [8] Kuzilek, Hlosta & Zdrahal, "Open University Learning Analytics dataset," *Scientific Data* (2017): https://www.nature.com/articles/sdata2017171 · UCI: https://archive.ics.uci.edu/dataset/349/open+university+learning+analytics+dataset
- [9] 1EdTech specifications: https://www.1edtech.org/specifications
- [10] Edlink, "Who creates data standards for education?" (CEDS description): https://ed.link/community/data-standardization-in-education/ (official site ceds.ed.gov not fetched)
- [11] College Scorecard data: https://collegescorecard.ed.gov/data/ · Institution-level data documentation: https://collegescorecard.ed.gov/assets/InstitutionDataDocumentation.pdf

---

## 12. Automotive (OEM, dealerships, after-sales)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **New-vehicle sales · SAAR** | Units retailed (plus fleet), and the seasonally adjusted annual rate | Market × month | Cox Automotive: 1.38M new sales in Aug 2026; 2026 full-year forecast 15.8M [1] | OEM wholesale shipments to dealers (sell-in) vs retail deliveries (sell-through). Fleet vs retail mixed. Sale vs registration date. |
| **Days' supply** | Inventory units ÷ daily selling rate at recent pace | Model/brand × market × month | Cox Automotive: 73 days' supply of new vehicles, Aug 2026 [1] | Inconsistent inventory (in-transit vs on-lot) and pace windows. Averaging ratios across models. |
| **ATP · incentive spend** | Average price actually paid. Incentives per unit and as % of ATP | Vehicle sale | Kelley Blue Book/Cox: ATP $50,089 in Aug 2026 [1]. Incentive share not captured in this pass | Reading mix shift (trucks, luxury, top trims) as price increase. MSRP vs transaction price. Fees and taxes in or out. |
| **Dealer gross per vehicle retailed · F&I per vehicle** | (Selling price − vehicle cost ± holdback/incentives) per retail unit. F&I income (finance reserve, service contracts, GAP) ÷ retail units | Deal | No verified public benchmark; NADA's full report is a download [2] | Fleet and wholesale units in the denominator. Front-end and back-end gross mixed. |
| **Service absorption** | Fixed-operations gross profit (service, parts, body shop) ÷ total dealership fixed overhead | Dealership × month | None verified. Context: NADA 2025 — 16,990 franchised light-vehicle dealers sold 16.2M vehicles, >$1.3T total sales, >$164B service & parts sales [2] | Overhead definitions differ (floorplan interest, owner compensation). Compare only like-for-like definitions. |
| **Repair-order productivity** (RO count, hours per RO, effective labour rate) | Labour sales ÷ hours sold. Hours sold ÷ ROs. Split by pay type: customer-pay, warranty, internal | RO / RO line | None verified | Blending pay types. Flagged hours vs clocked hours (efficiency vs productivity). |
| **Warranty claims rate · cost per vehicle** | Claims paid (or accruals) ÷ product sales, or per vehicle, by model year × months in service | MY × MIS cohort | Warranty Week: US-based automakers set records for claims paid and reserves held in Q2 2026 (qualitative) [3] | Calendar-period comparisons. Immature recent cohorts look cheaper because claims lag. |
| **Recall remedy completion rate** | Vehicles remedied ÷ vehicles affected, per campaign | Recall × VIN | None verified in this pass | Scrapped or exported vehicles left in the denominator. |
| **Inspection failure rate** (e.g. UK MOT) | Failed tests ÷ tests, by make/model/age/mileage | Test | Computable from DfT open data [4] | Not controlling for age and mileage. Retests counted as first tests. |
| **Used-vehicle turn** (days to sale, aged inventory %) | Acquisition → retail sale days. Share of units over 60/90 days | VIN | None verified | Reconditioning time excluded. Wholesale exits silently dropped. |

### Playbook

1. **Retail sales fall** (OEM or dealer group). Check in order:
   1. Days' supply by model and trim — constrained vs excess.
   2. ATP vs incentives vs competitors.
   3. Credit availability and payment affordability [1].
   4. Lead volume and lead-to-sale conversion.
   5. Model changeover timing.
   6. Fleet vs retail mix.

   *Action:* re-allocate incentives, dealer trades, subvented rates, marketing.
2. **Days' supply rises.** Check in order:
   1. Production vs sales pace.
   2. Trim/colour mix mismatch.
   3. Price positioning.
   4. Shipments in the pipeline.
   5. Model-year sell-down.

   *Action:* production cuts, incentives, dealer transfers.
3. **Dealer gross profit falls.** Check in order:
   1. New-vehicle gross: pricing, inventory age, floorplan cost.
   2. Used-vehicle gross: acquisition cost, reconditioning, aging.
   3. F&I per unit: product penetration, rate markups.
   4. Volume.

   *Action:* aging policy, F&I menu review, sourcing.
4. **Service absorption falls.** Check in order:
   1. RO count: appointment capacity, technician headcount.
   2. Effective labour rate: discounting, warranty mix.
   3. Hours per RO: inspection upsell.
   4. Parts margin.
   5. Overhead growth.

   *Action:* technician hiring, pricing, express service lanes.
5. **Warranty cost rises.** Cut by model year × months in service, then check in order:
   1. Component and labour op codes.
   2. Supplier part lots.
   3. Outlier dealers (claim-rate audits).
   4. Repeat repairs.

   *Action:* supplier recovery, engineering fix, service campaign or recall, dealer audit.
6. **Complaints or inspection failures rise for a model.** Adjust for age and mileage, then check in order:
   1. Failure items.
   2. Geography.
   3. Build plant and period (VIN decode) [6].

   *Action:* technical service bulletins, campaigns.

### Ontology sketch

**Objects (27).** OEM · Brand · Model · Model Year · Trim/Configuration · Vehicle (VIN) · Plant · Production Order · Dealer · Dealer Group · Wholesale Shipment · Inventory Unit · Customer · Lead · Deal (retail / lease / fleet) · F&I Contract · Trade-in · Floorplan Loan · Repair Order · RO Line (op code) · Technician · Part (fitment + attributes) · Warranty Claim · Recall Campaign · Recall Remedy · Telematics Event (DTC) · Inspection Test.

**Links**
- OEM 1:N Brand 1:N Model 1:N Model Year 1:N Trim.
- Vehicle N:1 Trim. Vehicle N:1 Plant (decodable from the VIN [5][6]).
- Vehicle 1:N Wholesale Shipment → Dealer. Dealer N:0..1 Dealer Group.
- Deal N:1 Vehicle. Deal N:1 Customer. Deal 1:N F&I Contract. Deal 0..N Trade-in.
- Customer N:M Vehicle (ownership over time).
- RO N:1 Vehicle. RO N:1 Dealer. RO 1:N RO Line N:1 Technician. RO Line N:M Part.
- RO Line (warranty pay type) 1:0..1 Warranty Claim.
- Recall Campaign N:M Vehicle (affected VIN list).
- Remedy N:1 Campaign. Remedy N:1 Vehicle. Remedy N:1 RO.
- Inspection Test N:1 Vehicle.
- Part N:M vehicle configuration (fitment) [8].

**Lifecycles**
- *New vehicle:* ordered → built → in transit → dealer stock → **retail delivered** → in operation → **scrapped / exported** ∎.
- *Used vehicle:* acquired (trade-in, auction) → reconditioning → frontline-ready → **retailed** ∎ / **wholesaled** ∎.
- *Deal:* lead → appointment → test drive → proposal → contracted → funded → **delivered** ∎. Or **lost** ∎ / **unwound** ∎.
- *Repair order:* appointment → write-up → dispatched → in progress ↔ waiting parts → completed → **invoiced / closed** ∎. A comeback (repeat repair) links back to the original RO.
- *Warranty claim:* submitted → approved → **paid** ∎. Or rejected → resubmitted; **charged back after audit** ∎.
- *Recall:* defect determined → filed → owner notification → remedy available → remedies performed → **campaign closed** ∎.

**Processes & promises**
- Quoted delivery date.
- RO promise time.
- Warranty coverage by time and mileage.
- Regulatory recall notification and remedy.
- Lender funding windows.

### Systems & standards

- **Systems:**
  - DMS: CDK Global, Reynolds and Reynolds.
  - Dealer CRM.
  - Inventory pricing tools.
  - F&I menu systems.
  - OEM dealer and warranty portals.
  - OEM ERP/MES: SAP.
  - Connected-vehicle and telematics platforms.
  - Electronic parts catalogues.
  - Remarketing auctions.
- **Standards:**
  - **VIN**: ISO 3779/3780; 17 characters = WMI (1–3), VDS (4–9, check digit in position 9 in North America), VIS (10–17, model year in 10, plant in 11); governed in the US by 49 CFR 565 [5].
  - **NHTSA vPIC API**: VIN decode, WMI, makes/models, batch decoding [6].
  - **STAR**: XML BODs (STAR5/STAR6) and sales and service-scheduling APIs between dealers, OEMs and system providers [7].
  - **ACES**: fitment data via VCdb/PCdb/Qdb [8].
  - **PIES**: product attributes, pricing, warranty, interchange [9].

### Validation datasets

1. **UK DfT Anonymised MOT tests and results** [4].
   - Content: OGL v3, 2005–2023, separate annual files for test results and failure items, with a user guide and lookups. Fields include make, model, odometer reading, fuel type, test outcome and failure items.
   - *Computes:* failure rate by make/model/age/mileage, annual mileage (usage), defect categories, retest rates, and a survival proxy (vehicles leaving the test population).
2. **NHTSA vPIC** [6].
   - *Computes:* VIN enrichment (make, model, model year, plant, body) for any VIN-bearing table. Rate-limited API.
3. NHTSA complaints/recall flat files would add quality validation but were **not verified in this pass** (§17).

No public dealer DMS data exists — F&I, absorption and RO metrics cannot be validated openly (§16).

### What generic analytics gets wrong here

- It treats OEM wholesale shipments as consumer demand — the CPG sell-in/sell-through trap again.
- It reads ATP growth as pricing power when mix shifted to trucks, luxury or higher trims, and ignores incentives.
- It compares warranty cost across calendar periods instead of model-year × months-in-service cohorts, so immature cohorts look better.
- It computes days' supply with inconsistent inventory definitions and sales-pace windows.
- It blends customer-pay, warranty and internal repair orders in labour-rate and hours-per-RO metrics.

### Sources

- [1] Cox Automotive Market Insights (updated 10 Sep 2026): https://www.coxautoinc.com/market-insights/
- [2] NADA Data (2025 full-year highlights): https://www.nada.org/nadadata
- [3] Warranty Week (8 Sep 2026 newsletter): https://www.warrantyweek.com/
- [4] DfT, Anonymised MOT tests and results: https://www.data.gov.uk/dataset/e3939ef8-30c7-4ca8-9c7c-ad9475cc9b2f/anonymised_mot_test
- [5] Vehicle identification number (ISO 3779/3780, 49 CFR 565): https://en.wikipedia.org/wiki/Vehicle_identification_number
- [6] NHTSA vPIC API: https://vpic.nhtsa.dot.gov/api/
- [7] STAR, Standards for Technology in Automotive Retail: https://www.starstandard.org/
- [8] Auto Care Association, ACES: https://www.autocare.org/aces
- [9] Auto Care Association, PIES: https://www.autocare.org/pies

---

## 13. B2B marketplaces & wholesale distribution

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Line fill rate · order fill rate** | Lines (or units) shipped complete on first shipment ÷ lines ordered. Orders shipped complete ÷ orders | Order line | No verified public benchmark | Mixing units, lines and orders. Backorders filled later counted as filled. |
| **OTIF · perfect order** | Orders on time (vs a *fixed* reference date) and in full ÷ orders. Perfect order adds damage-free and correctly invoiced | Order | No verified public benchmark | Moving the reference date (requested → confirmed → revised). Partial credit for part-filled orders. |
| **Gross margin % · GMROI** | (Sales − COGS) ÷ sales. Gross margin $ ÷ average inventory at cost | SKU × location × period | No verified figure. Census AWTS covered wholesale; now folded into AIES [1] | Vendor rebates booked late, so margin is restated. Average inventory from month-end snapshots only. |
| **Inventory-to-sales ratio · turns** | Inventory ÷ monthly sales. COGS ÷ average inventory | Location × month | Census publishes monthly merchant-wholesaler inventories/sales ratios by kind of business [2]. Scale: US merchant wholesalers sold $11,382.3B in 2022, +17.4% YoY [1] | Cost vs retail valuation. Consignment and VMI stock in or out. |
| **DSO · dispute rate** | Receivables ÷ sales × days. Disputed invoices ÷ invoices | Customer × period | None verified | Unapplied cash. Seasonal sales distort DSO. |
| **Price realisation · leakage** (pocket-price waterfall) | Pocket price ÷ list price, after off-invoice discounts, rebates, freight allowances, payment-terms cost | Invoice line | None verified | Using invoice price as the realised price. |
| **Cost-to-serve · order profitability** | Gross margin − activity costs (order entry, picking, freight, returns, credit) per order or customer | Order / customer | None verified | Allocating costs by revenue instead of activity drivers, which hides small-order losses. |
| **Contract compliance** (buyer side) | Spend on contracted items and suppliers ÷ total spend | PO line | None verified | UNSPSC/ECLASS misclassification [6][8]. |
| **Marketplace GMV · take rate · active buyers & sellers · seller activation** | GMV = order value (define treatment of cancellations and returns). Take rate = revenue ÷ GMV. Activation funnel: lead → contacted → deal closed → first sale | Order / seller | Olist funnel data: 8,000 marketing-qualified seller leads (Jun 2017–Jun 2018) linkable to ~100k orders via seller_id [3] — dataset scale, not a benchmark | Counting signed sellers as supply before first sale. Cancelled orders in GMV. |

### Playbook

1. **Revenue falls.** Normalise for selling days first; distribution revenue is business-day driven. Then check in order:
   1. Active accounts vs revenue per account.
   2. Loss of a top account or contract (concentration).
   3. Price vs volume vs mix (pocket price).
   4. End-market exposure.
   5. Stockouts causing lost sales (fill rate).
   6. Channel shift to punch-out, portals or marketplaces.

   *Action:* account plans, pricing, inventory positioning.
2. **Gross margin falls.** Check in order:
   1. Price realisation: discount approvals, contract prices lagging cost inflation.
   2. Vendor rebate attainment.
   3. Customer and product mix.
   4. Freight cost recovery.
   5. Inventory write-downs.

   *Action:* cost pass-through, rebate plans, freight surcharges.
3. **Fill rate or OTIF falls.** Check in order:
   1. Supplier fill rate and lead-time changes.
   2. Forecast error on top SKUs.
   3. Safety-stock settings.
   4. DC labour and capacity.
   5. Carrier performance.
   6. Order acknowledgement mismatches (X12 855) [4].

   *Action:* safety-stock reset, supplier escalation, expediting.
4. **DSO rises.** Check in order:
   1. Disputes: pricing errors, shortages, missing proof of delivery.
   2. Invoice errors.
   3. Customer mix toward longer terms.
   4. Collections capacity.

   *Action:* dispute root-cause fixes, structured e-invoicing (Peppol) [7], terms enforcement.
5. **Marketplace GMV falls.** Split into active buyers × order frequency × AOV. Check in order:
   1. Active sellers and in-stock listings.
   2. Search-to-order conversion.
   3. Delivery vs estimate and review scores [10].
   4. Seller activation funnel and seller churn [3].

   *Action:* seller onboarding, buyer promotions, logistics fixes.

### Ontology sketch

**Objects (23).** Buyer Account (company) · Location (ship-to/bill-to, GLN) · Buyer Contact · Supplier/Vendor · Marketplace Seller · Product (SKU/GTIN, classified by UNSPSC or ECLASS) · Price List / Contract Price · RFQ/Quote · Customer PO · Sales Order · Order Line · Allocation/Backorder · Shipment (ASN) · Proof of Delivery · Invoice · Credit Memo / Dispute · Payment / Remittance · Rebate Agreement · Inventory Position (SKU × DC) · Distribution Centre · Return (RMA) · Seller Lead · Listing (offer).

**Links**
- Account 1:N Location. Account 1:N Contact. Account N:M Contract Price List.
- Sales Order N:1 Account. Sales Order N:1 Ship-to. Sales Order 1:N Line N:1 Product.
- Line 1:N Allocation (partials and backorders).
- Order 1:N Shipment (splits). Shipment N:M Line. Shipment 1:0..1 Proof of Delivery.
- Invoice N:M Shipment (consolidated billing). Invoice 1:N Credit Memo.
- Payment N:M Invoice (remittance allocation).
- Product N:M Supplier. Rebate Agreement N:1 Supplier. Rebate Agreement N:M Product.
- Inventory Position N:1 DC.
- Listing N:1 Seller. Listing N:1 Product. Order Line N:1 Listing.
- Seller 1:0..1 Seller Lead.

**Lifecycles**
- *RFQ/quote:* requested → quoted → negotiated → **accepted → order** ∎. Or **expired** ∎ / **lost** ∎.
- *Sales order:* received (EDI 850, punch-out, portal) → acknowledged (855) → credit check → allocated → picked → shipped with ASN (856) → delivered (POD) → invoiced (810) → **paid** ∎. Or **cancelled** ∎. Backordered lines ship later [4].
- *Invoice:* issued → due → **paid** ∎. Or disputed → credit memo → **closed** ∎; **written off** ∎.
- *RMA:* requested → authorised → received → inspected → **credited / replaced** ∎. Or **rejected** ∎.
- *Marketplace seller:* lead → contacted → consultancy → **deal closed** → catalogue built → first sale → active → **churned** ∎ [3].

**Processes & promises**
- Order acknowledgement time.
- Quoted lead time and ship-by date.
- Delivery window.
- Payment terms (net 30/60).
- Rebate settlement periods.
- Dispute resolution windows.
- E-invoicing obligations where mandated [7].

### Systems & standards

- **Systems:**
  - Distribution ERP: SAP, Oracle, Epicor Prophet 21, Infor.
  - WMS/TMS.
  - B2B e-commerce and punch-out to buyer procurement suites: SAP Ariba, Coupa.
  - EDI VANs and PIM.
  - Pricing/CPQ: PROS, Zilliant.
  - Rebate management.
  - Marketplaces: Amazon Business, Faire, Alibaba.com.
- **Standards:**
  - **X12** transaction sets [4].
  - **UN/EDIFACT**, maintained by UN/CEFACT [5].
  - **Peppol**: OpenPeppol network for e-invoices, orders and other business documents [7].
  - **UNSPSC**: 8-digit, four-level segment/family/class/commodity taxonomy; governance returned to UNDP from GS1 US on 31 Dec 2024 [6].
  - **ECLASS**: ISO/IEC-compliant product classification and properties, Release 16.0 [8].
  - **GS1** GTIN/GLN (§3).

### Validation datasets

1. **UCI Online Retail II** [9].
   - Content: 1,067,371 invoice lines, 1 Dec 2009–9 Dec 2011, a UK online gift-ware seller whose customers include many wholesalers. Invoice numbers starting with "C" are cancellations. Fields: invoice, stock code, description, quantity, date, unit price (GBP), customer ID, country.
   - Licence: CC BY 4.0.
   - *Computes:* customer concentration, buyer cohort retention, order frequency, cancellation/credit rate, quantity-break price variation, country mix.
   - *Cannot compute:* margin, inventory, fill rate.
2. **Olist Marketing Funnel + Brazilian E-Commerce** [3][10].
   - Content: 8k seller leads through SDR and closer stages, joined by seller_id to ~100k marketplace orders (2016–2018) with status, payments, estimated vs actual delivery, reviews.
   - Licence: CC BY-NC-SA 4.0.
   - *Computes:* seller-acquisition funnel conversion, time to first sale, GMV by seller cohort, delivery vs promise, review impact.
3. **DataCo Smart Supply Chain** (Mendeley) [11].
   - Content: order-level supply-chain records (clothing, sports, electronics) with a variable-description file.
   - Licence: CC BY 4.0.
   - *Computes:* late-delivery rate, real vs scheduled shipping days, profit per order, segment mix. Verify fields against the description file.

### What generic analytics gets wrong here

- It compares months without selling-day normalisation.
- It treats invoice price as realised price, ignoring rebates, allowances, freight and payment terms.
- It measures fill and OTIF against moving reference dates, or switches between units, lines and orders.
- It allocates cost-to-serve by revenue, which hides unprofitable small orders and customers.
- It counts signed marketplace sellers as supply and cancelled orders as GMV.

### Sources

- [1] US Census Bureau, Annual Wholesale Trade Survey (now part of AIES): https://www.census.gov/programs-surveys/awts.html
- [2] US Census Bureau, Monthly Wholesale Trade: https://www.census.gov/wholesale/index.html
- [3] Kaggle, Marketing Funnel by Olist (8k leads; CC BY-NC-SA 4.0): https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist
- [4] X12: https://x12.org/
- [5] UN/EDIFACT: https://en.wikipedia.org/wiki/EDIFACT
- [6] UNSPSC: https://en.wikipedia.org/wiki/UNSPSC
- [7] Peppol (OpenPeppol): https://peppol.org/
- [8] ECLASS: https://eclass.eu/en/
- [9] UCI Online Retail II: https://archive.ics.uci.edu/dataset/502/online+retail+ii
- [10] Kaggle, Brazilian E-Commerce Public Dataset by Olist: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
- [11] DataCo Smart Supply Chain (Mendeley Data): https://data.mendeley.com/datasets/8gx2fvg2k6/5

---

## 14. Professional services / agencies (brief)

### KPIs

| KPI (aliases) | Definition · formula | Grain | Benchmark / sane range (source) | Anti-patterns |
|---|---|---|---|---|
| **Billable utilisation** | Billable hours ÷ available hours. Declare "available": standard hours vs capacity net of holidays and PTO | Person × week | SPI 2025 PS Maturity Benchmark (403 organisations, ~150k consultants): Level-5 firms show +36.4% billable utilisation vs Level-2 peers. Absolute figures are paywalled [1] | Denominators differing across teams. Non-billable client work counted as billable. |
| **Billing realisation** | Billed value ÷ standard value of time worked (hours × standard rate) | Matter/project × period | None verified | Pre-bill write-downs mixed with post-bill write-offs. |
| **Collection realisation** | Collected ÷ billed | Invoice cohort | None verified | Cash timing — use aged invoice cohorts. |
| **Effective rate** | Fees collected ÷ hours worked | Person / matter | None verified | Fixed-fee matters and discounts ignored. |
| **Leverage** | Delivery staff ÷ partners (or managers) | Firm / practice | None verified | Contractors excluded. |
| **Lock-up** (WIP days + debtor days) | Unbilled WIP ÷ daily fees + receivables ÷ daily fees | Firm × month | None verified | WIP valued at standard rather than realisable value. |
| **Project margin** | (Revenue − fully loaded delivery cost) ÷ revenue | Project | SPI: Level-5 firms +265% EBITDA vs Level 2 (comparative only) [1] | Salary-only cost instead of fully loaded. |
| **Revenue per billable consultant** | Revenue ÷ *average* billable headcount | Period | None verified | End-of-period headcount. |

### Playbook

1. **Margin falls.** Check in order:
   1. Utilisation: bench and internal time.
   2. Realisation: fixed-fee overruns, discounts.
   3. Staffing pyramid mix.
   4. Subcontractor cost.
   5. Scope creep without change orders.

   *Action:* re-staffing, change orders, pricing.
2. **Utilisation falls.** Check in order:
   1. Backlog coverage vs capacity.
   2. Delayed project starts.
   3. Skills mismatch.
   4. Hiring ahead of demand.

   *Action:* redeploy, slow hiring, sales push.
3. **Lock-up rises.** Check in order:
   1. Late timesheets.
   2. Milestone billing disputes.
   3. Client terms.
   4. E-billing rejections — LEDES/UTBMS coding errors [2].

   *Action:* timesheet compliance, billing-operations fixes.
4. **Realisation falls.** Check in order:
   1. Estimate accuracy on fixed-fee work.
   2. Client rate agreements.
   3. Billing-guideline rejections.
   4. Write-offs by engagement lead.

   *Action:* estimation discipline, pricing.

### Ontology sketch

**Objects (17).** Client · Engagement/Matter · Contract/SOW · Rate Card · Project · Phase/Task (UTBMS task code for legal) · Resource (employee / contractor) · Role/Skill · Assignment · Timesheet Entry · Expense · WIP · Invoice · Payment · Write-down/Write-off · Opportunity · Change Order.

**Links**
- Client 1:N Engagement 1:N Project 1:N Task.
- Engagement N:1 SOW N:1 Rate Card.
- Timesheet Entry N:1 Resource. Timesheet Entry N:1 Task.
- Invoice Line N:M Timesheet Entry. Payment N:M Invoice.
- Opportunity 0..1:1 Engagement.
- Assignment N:1 Resource. Assignment N:1 Project.

**Lifecycles**
- *Opportunity:* qualified → proposal → **won** ∎ / **lost** ∎.
- *Project:* planned → active ↔ on hold → completed → **closed** ∎. Or **cancelled** ∎.
- *Time entry:* draft → submitted → approved → billed (WIP relieved) → **collected** ∎. Or **written off** ∎.
- *Invoice:* draft → issued/e-billed → accepted or rejected (appeal) → **paid** ∎.

**Processes & promises**
- Timesheet deadlines.
- Monthly billing cycle.
- Client billing guidelines and appeals.
- SOW change control.

### Systems & standards

- **Systems:**
  - PSA: Kantata, Certinia, Deltek Vantagepoint/Maconomy.
  - Legal practice management: Elite 3E, Aderant, Clio.
  - ERP/HR: Workday.
  - CRM.
- **Standards:**
  - **LEDES** e-billing formats (98B, 2000, XML 2.x) and timekeeper data.
  - **UTBMS** task, activity and expense codes [2].

### Validation datasets

**None realistic found.** No public timesheet, billing and collections data was located; validation needs synthetic data or a design partner (§16).

### What generic analytics gets wrong here

- It uses inconsistent utilisation denominators: standard hours vs capacity net of PTO.
- It conflates billing realisation, collection realisation and effective rate, and computes realisation before write-downs post.
- It computes project margin on salary-only cost, pushing non-billable time into invisible overhead.

### Sources

- [1] SPI Research, 2025 Professional Services Maturity Benchmark: https://spiresearch.com/reports/2025-ps-maturity-benchmark/
- [2] LEDES Oversight Committee (LEDES formats, UTBMS codes): https://ledes.org/

---

## 15. GAP CHECK — the six existing packages

*Only items a typical "GMV/AOV", "OTP/yield", "OEE/FPY" or "MRR/NRR/churn" treatment misses. Benchmarks appear only where a source was fetched in this pass.*

### 15.1 E-commerce / retail

- **KPIs to add:**
  - Returns rate and net sales after returns — US returns projected at $890B in 2024 [G1].
  - Contribution margin per order after fulfilment, returns, payment fees and marketing.
  - Sell-through % and GMROI.
  - OOS rate (8.3% worldwide, §3 [8]) and shrink (1.6% of sales, §4 [3]).
- **Ontology to add:**
  - Return/RMA: requested → received → inspected → **refunded / exchanged** ∎ or **rejected** ∎.
  - Order 1:N Shipment (split fulfilment).
  - Inventory Position per location.
  - Order Line N:0..1 Promotion/Coupon.
- **Playbook entry:** *Net revenue falls while GMV is flat* → check in order: return rate by category and size, cancellations, discount depth, payment failures.
- **Anti-pattern:** GMV and AOV computed before cancellations and returns.

### 15.2 Airline

- **On-time is a threshold indicator.** BTS flags arrivals and departures 15+ minutes late (ArrDel15/DepDel15). Cancellations and diversions are separate indicators. Delay minutes split into carrier, weather, NAS, security and late-arriving aircraft [G2].
  - *Gap:* pair OTP with completion factor (operated ÷ scheduled), or an airline can "improve" OTP by cancelling.
  - *Gap:* separate root delay from propagated (late-aircraft) delay.
- **Ontology:** IATA ONE Order replaces PNR, e-ticket and EMD with a single Order [G3]. Model Offer → Order → Order Item/Service separately from Flight → Leg → Segment, and keep marketing vs operating carrier distinct.
- **KPIs to add (no benchmarks verified):**
  - CASM excluding fuel, stage-length adjusted.
  - Ancillary revenue per passenger.
  - Misconnect rate.
  - Mishandled-bag rate, using the DOT report's own denominator [G4].
- **Playbook entry:** *OTP falls* → split delay minutes by BTS cause. A rising late-aircraft share means propagation; fix first-wave departures and turn buffers.

### 15.3 Food delivery

- **Definition traps (verified), DoorDash** [G5]:
  - *Total Orders* **includes** Commerce Platform orders; *Marketplace GOV* **excludes** them. Marketplace GOV ÷ Total Orders is therefore not AOV.
  - GOV includes taxes, **tips** and consumer fees, including DashPass/Wolt+ membership fees.
  - Q4 2024: 685M orders, $21.3B Marketplace GOV, $2.873B revenue, net revenue margin 13.5% (= revenue ÷ Marketplace GOV).
- **Cross-company comparisons need tip and discount normalisation:**
  - Uber Delivery Gross Bookings **exclude** tips (§9 [1]).
  - Instacart GTV **includes** tips (§4 [2]).
  - Eternal moved to NOV because restaurant-funded discounts inflate GOV (§4 [6]).
- **Ontology to add:**
  - Order vs Delivery vs Courier Offer/Assignment (batching: Route 1:N Delivery).
  - Refund/Credit as a cost object (missing or wrong items).
  - Merchant menu-item availability.
- **KPIs to add (no benchmarks verified):**
  - Order defect rate (missing / wrong / late / never delivered).
  - Refunds & credits as % of GOV.
  - Courier active-time share.
  - ETA accuracy.
  - Batch rate.
- **Playbook entry:** *Contribution per order falls* → check in order: refunds and credits, courier pay per delivery (distance, merchant wait), consumer promotions, membership-fee dilution.

### 15.4 Logistics

- **Detention and dwell** (DOT OIG, 2018) [G6]:
  - A 15-minute increase in average dwell time raises the expected crash rate by **6.2%**.
  - Detention reduces for-hire truckload drivers' annual earnings by **$1.1–1.3B**, and carriers' net income by **$250.6–302.9M**.
  - Industry data records only time beyond contractual free time, so true detention goes unmeasured.
- **KPIs to add:**
  - Dwell time per facility (arrival → departure, including free time).
  - Detention hours, and detention charges billed vs collected.
  - Appointment adherence.
  - Tender acceptance/rejection rate.
  - Empty (deadhead) miles %.
  - First-attempt delivery success.
  - Claims/damage rate.
- **Ontology to add:** Shipment N:M Load (consolidation) · Stop · Tender (offer to carrier) · Appointment · Accessorial Charge. X12 carries the tender/status/freight-invoice documents (§3 [10]).
- **Playbook entry:** *Cost per load rises* → accessorials by facility → dwell distribution → appointment compliance → shipper facility scorecards.
- **Anti-pattern:** on-time measured against re-planned appointments.

### 15.5 Manufacturing

- **OEE caution** [G7]:
  - "World-class" 85% = 90% availability × 95% performance × 99% quality, from 1970s Japanese automotive practice. Typical plants run around 60%.
  - Lines with different product mixes should not be compared on OEE.
- **KPIs to add:**
  - TEEP (OEE × loading).
  - Planned vs unplanned downtime.
  - MTBF / MTTR.
  - Changeover time.
  - Rolled throughput yield (product of step yields) vs FPY.
  - Schedule attainment.
  - Cost of poor quality.
- **Ontology to add, using ISA-95/IEC 62264 names** [G8]: equipment hierarchy · material lot/sublot (genealogy) · work/job order · process/operations segment · production schedule and performance · downtime event with reason code · quality test. The standard addresses the Level-3 (MES) ↔ Level-4 (ERP) boundary.
- **Playbook entry:** *OEE falls* → which factor? Availability: unplanned downtime by reason and MTTR. Performance: minor stops and speed loss. Quality: scrap by defect and lot.
- **Anti-pattern:** averaging OEE across lines or shifts instead of weighting by planned production time.

### 15.6 SaaS

- **Definitions** (SaaS Capital 2025) [G9]:
  - NRR = December-2024 MRR from customers who were customers in December 2023 ÷ total December-2023 MRR.
  - GRR = the same, excluding upsell, cross-sell and price increases, so it is capped at 100%.
  - Median NRR: **102%** at $25–50k ACV, **107%** at $100–250k ACV. Higher ACV means higher NRR.
- **KPIs to add:**
  - GRR next to NRR.
  - Logo vs revenue churn.
  - ARR waterfall: new, expansion, contraction, churn, reactivation.
  - CAC payback.
  - Cohort NRR.
  - Seat/usage utilisation as a leading churn indicator.
  - Billings vs revenue vs ARR.
- **Ontology to add:**
  - Subscription Line (product × quantity × price × term), Contract/Order Form, Entitlement/Seat, Usage Event.
  - Lifecycle: trial → active → renewal due → renewed / expanded / contracted → **churned** ∎.
- **Playbook entry:** *NRR falls* → split GRR (churn + contraction) from expansion, then cut by ACV band [G9], cohort and product usage.
- **Anti-patterns:** new customers in the NRR numerator; NRR compared across ACV bands.

### Sources (gap check)

- [G1] NRF & Happy Returns, 2024 Consumer Returns in the Retail Industry: https://nrf.com/research/2024-consumer-returns-retail-industry
- [G2] BTS TranStats field definitions (ArrDel15, delay causes): https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ
- [G3] IATA ONE Order: https://www.iata.org/en/programs/airline-distribution/retailing/one-order/
- [G4] US DOT Air Travel Consumer Reports: https://www.transportation.gov/individuals/aviation-consumer-protection/air-travel-consumer-reports (blocked to fetch)
- [G5] DoorDash Q4 2024 results (definitions): https://www.sec.gov/Archives/edgar/data/1792789/000162828025004877/dashq42024ex991-pressrelea.htm
- [G6] DOT Office of Inspector General, Report ST2018019 (31 Jan 2018): https://www.oig.dot.gov/sites/default/files/FMCSA%20Driver%20Detention%20Final%20Report.pdf
- [G7] OEE.com, "World-Class OEE": https://www.oee.com/world-class-oee/
- [G8] ISA, ISA-95 standard: https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard
- [G9] SaaS Capital, 2025 SaaS Retention Benchmarks for Private B2B Companies: https://www.saas-capital.com/research/saas-retention-benchmarks-for-private-b2b-companies/

---

## 16. Cross-industry note

### Candidate shared base packages

| Base package | Industries | Shared objects | Shared KPIs | Definition traps to encode once |
|---|---|---|---|---|
| **core-commerce** | e-commerce, grocery, CPG, restaurants, automotive parts, B2B | Product/SKU (GTIN) · Order/Check/Transaction → Line · Price · Promotion · Return · Inventory Position · Customer/Loyalty | Net sales · traffic × basket · comparable sales · OOS · shrink · gross margin · GMROI | Comparable-sales eligibility differs (13 months McDonald's; 13 full calendar months Chipotle; 5 full quarters, excl. fuel, Kroger). Sell-in vs sell-through (CPG, automotive, wholesale). |
| **core-marketplace** | OTA, STR, food delivery, ride-hail, quick commerce, B2B marketplaces | Buyer · Seller/Supplier · Listing/Offer · Order/Booking · Payout · Commission | Gross bookings/GOV/GTV/GMV · take rate · active buyers and suppliers · fulfilment / cancellation | Carry an **inclusion flag per measure**: taxes, fees, tips, cancellations, membership fees. Uber GB excludes tips; DoorDash GOV and Instacart GTV include them; Expedia GB is net of cancellations; Airbnb GBV includes taxes and cleaning fees. Also a **principal/agent flag**: Eternal's move to owned inventory lifted revenue +172% vs +65% like-for-like. |
| **core-subscription** | streaming, SaaS, consumer edtech, game passes, delivery memberships | Account · Subscription · Plan · Invoice · Payment Attempt · Entitlement | Gross vs net churn · resubscribers · ARPU on average daily subscribers · NRR/GRR | Grace periods and family sub-accounts counted as subscribers (Spotify). About a third of gross adds are resubscribers (Antenna). |
| **core-capacity** (revenue management) | hotels, airlines, restaurants, car rental | Capacity unit × time slot · Reservation · Rate/Fare · Competitive Set | Occupancy / load factor / utilisation · yield (ADR, RPD) · revenue per available unit (RevPAR, RevPASH, RASM) · index vs comp set | Divide by *available*, not sold. Keep booking date vs service date explicit. Cancellations and no-shows as cohorts. |
| **core-transport** | airline, logistics, ride-hail, car rental, couriers | Trip/Leg/Stop · Vehicle/Asset · Driver/Crew · Schedule vs Actual | On-time (threshold-based, e.g. BTS 15 min) · dwell/wait · deadhead/idle · utilisation | Utilisation denominators (en-route and idle time; held-for-sale vehicles). Wait times measured on completed trips only. |
| **core-engagement** (cohorts) | gaming, media, edtech, consumer apps | User · Session · Event · Install/Signup Cohort | DAU/MAU · day-N retention (classic vs rolling) · session metrics | Pool users, never average cohort percentages. Benchmark samples change between report years. |
| **core-advertising** | adtech, media, retail media, CPG, marketplace ad businesses (Instacart ads = 2.9% of GTV) | Campaign · Line Item · Creative · Impression → Viewable → Click → Conversion · Attribution Touch | Viewability · IVT · CTR/CPC/CVR · ROAS vs iROAS | MRC measured vs served denominators. Attribution ≠ incrementality. |
| **core-workforce** | restaurants, professional services, ride-hail, dealer service, manufacturing | Employee/Resource · Shift/Assignment · Time Entry | Labour % of sales · utilisation · productivity | Declare the "available hours" denominator. |
| **core-b2b-documents** | CPG, grocery, wholesale, automotive, manufacturing, logistics | PO → Acknowledgement → ASN → Invoice → Payment · Deduction/Dispute · GS1 identifiers | Fill rate · OTIF · DSO · deduction rate | Map X12, EDIFACT and Peppol names to one vocabulary. |
| **core-property** | real estate, hotel asset view, restaurant/retail occupancy cost | Asset · Space · Lease · Charge · Work Order | NOI · cap rate · physical vs economic occupancy | Trailing vs forward NOI. Appraisal smoothing. |

**Cross-cutting rules for the base layer:**
- Sum numerators and denominators at the declared grain, then divide.
- Every "comparable" measure carries an eligibility rule.
- Every benchmark carries date, population and source.
- Every monetary measure carries inclusion flags.

### Hardest industries to validate (no realistic public data found)

1. **Professional services.** No timesheet, billing or collections data.
2. **CPG sell-in vs sell-through and trade spend.** Nothing joins shipments, deductions and POS; %ACV/TDP need paid syndicated data.
3. **Automotive dealerships and warranty.** DMS, F&I, RO and warranty claims are proprietary; only UK MOT and NHTSA vPIC are open.
4. **Property management.** No rent-roll, lease or work-order data; only sale registries (UK Price Paid, NYC Rolling Sales).
5. **Restaurants.** No check-level POS joined to labour and food cost; only reservation/visit data (Recruit).
6. **Gaming monetisation.** No purchase-level IAP data; public benchmark reports omit monetisation.
7. **Car rental and quick-commerce dark stores.** No transaction-day or store-operations data.
8. **Adtech incrementality / MMM.** Criteo and iPinYou logs have no ground-truth lift.

### Licensing note for an open-source product

Many of the most realistic datasets are **non-commercial**: Instacart, MIND, MovieLens (commercial use needs permission), Criteo, trivago, EdNet, Olist. Use them for validation only and never bundle them.

- **Redistributable with attribution (CC BY):** Hotel booking demand, Inside Airbnb, OULAD, UCI Online Retail II, DataCo.
- **OGL:** UK MOT, HM Land Registry Price Paid.
- **US public-sector data** (check terms per dataset): NYC TLC, College Scorecard, NHTSA vPIC.

---

## 17. Not verified in this pass — do not ship as fact

- **Blocked pages** (definitions or figures used only "as indexed" or "as summarised"):
  - USALI current edition and HFTP page (403).
  - STR/CoStar glossary text (403).
  - WordStream benchmark pages (403).
  - DOT Air Travel Consumer Report page (403), so its mishandled-baggage denominator is unverified.
- **Standards named nowhere in this report because they were not checked:** NRA Uniform System of Accounts for Restaurants, ACRISS/SIPP car-class codes, NRF ARTS retail data model, cXML/OAGIS, MISMO, xAPI.
- **BOMA floor measurement standards:** page returned 404; IPMS cited instead.
- **NHTSA complaints/recalls/investigations flat files:** page returned 403; not described.
- **Omitted — no authoritative source reachable:**
  - Mobile-game payer-conversion benchmarks.
  - MOOC completion percentages (only the qualitative finding of Reich & Ruipérez-Valiente is used).
  - FMI 2024 grocery net margin (secondary sources only).
  - NIQ display-compliance statistic (secondary source only).
- **Dataset licence terms still to confirm:** Cookie Cats, WoWAH, Recruit Restaurant, KKBox, M5, Favorita, dunnhumby Complete Journey, iPinYou, Redfin Data Center.
- **CEDS:** described from a secondary source (Edlink); official site not fetched.
- **Summarised only, not read at source:** Antenna 2025 churn figure (~4.6%, via Deadline) and RealPage renewal figures (via search summaries).
