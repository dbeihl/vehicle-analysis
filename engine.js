/* Cost engine. The single implementation -- build.py inlines this into
   index.html, and test_engine.mjs imports it directly.

   Transliterated from the Python that produced data/engine-fixture.json.
   Expression order is deliberately identical: both runtimes use IEEE-754
   doubles, so matching order gives matching results. NO ROUNDING happens
   here. Python's round() is half-to-even and Math.round is not, so rounding
   lives at the display layer only. */
var VA = (function () {
  function retentionIndex(odometer, anchors) {
    var base = anchors[0][1];
    if (odometer <= anchors[0][0]) return anchors[0][1] / base;
    for (var i = 0; i < anchors.length - 1; i++) {
      var x0 = anchors[i][0], y0 = anchors[i][1];
      var x1 = anchors[i + 1][0], y1 = anchors[i + 1][1];
      if (odometer <= x1) {
        var span = (odometer - x0) / (x1 - x0);
        return (y0 + span * (y1 - y0)) / base;
      }
    }
    return anchors[anchors.length - 1][1] / base;
  }

  function repairReserve(inp) {
    var buy = inp.buy_odometer, sell = inp.sell_odometer;
    var r = inp.repair_reserve_per_mile;
    var bands = [
      [Math.max(0, Math.min(sell, 100000) - buy), r.under_100k],
      [Math.max(0, Math.min(sell, 150000) - Math.max(buy, 100000)), r['100k_to_150k']],
      [Math.max(0, sell - Math.max(buy, 150000)), r.over_150k]
    ];
    var total = 0;
    for (var i = 0; i < bands.length; i++) total += bands[i][0] * bands[i][1];
    return total / (sell - buy);
  }

  /* Fixed anchors, deliberately not the fleet's own min and max: a
     fleet-relative rescale would move every vehicle's cost whenever a row is
     added. The observed range is 0.219 (Toyota Venza) to 0.944 (Cadillac
     Escalade ESV), so these bracket it with a little headroom and a future
     outlier clamps instead of rescaling its peers. */
  var COMPLAINT_ANCHOR_LOW = 0.20, COMPLAINT_ANCHOR_HIGH = 0.95;

  function complaintScore(share) {
    var s = (COMPLAINT_ANCHOR_HIGH - share)
          / (COMPLAINT_ANCHOR_HIGH - COMPLAINT_ANCHOR_LOW);
    return Math.max(0, Math.min(1, s)) * 100;
  }

  function repairReliability(v, inp) {
    /* Per-model evidence wins wherever the model has enough of its own
       complaints to describe it. The prior is a fallback for the rows that
       have none, NOT a weight applied to the rows that do: it is
       brand-shaped, Toyota 85-100 against Jeep 17.4-42.4 with no overlap, so
       pulling a measured figure toward it averages across a badge.

       Turns off by raising complaint_min_n above every count, not by zeroing
       it -- the opposite of repair_cost_spread_ratio, whose neutral is 1. */
    if (v.complaintSeverity !== null && v.complaintSeverity !== undefined
        && v.complaintN >= inp.complaint_min_n) {
      return complaintScore(v.complaintSeverity);
    }
    return v.reliability;
  }

  function repairMultiplier(v, inp) {
    /* Geometric around reliability 50, with the exponent over the full
       0-100 scale, so inp.repair_cost_spread_ratio IS the worst-to-best
       ratio -- there is no second constant to keep in sync with it.

       Neutral is 1, not 0. Math.pow(0, x) returns 0 or Infinity and takes
       every cost per mile with it, which is worth stating because every
       other assumption in this model turns off at zero.

       Anchored at reliability 50 rather than at the fleet's median, because
       costPerMile sees one vehicle at a time: a fleet-relative anchor would
       move every vehicle's cost whenever a row is added. */
    return Math.pow(inp.repair_cost_spread_ratio,
                    (50 - repairReliability(v, inp)) / 100);
  }

  function resaleMultiplier(v, inp) {
    return (1 - v.deprec5yr) / (1 - inp.industry_avg_5yr_deprec);
  }

  function buyPrice(v, inp) {
    if (v.observedPrice) {
      /* Scale along this vehicle's own curve from a measured point. No
         resaleMultiplier is involved -- that is what made the retired MSRP
         derivation double-penalise fast-depreciating models. At the anchor
         the ratio is exactly 1 and the observed figure passes through. */
      /* Explicit null check, not truthiness: an anchor of 0 miles means the
         price was observed new, and must still scale. */
      if (v.observedAt !== null && v.observedAt !== undefined
          && v.observedAt !== inp.buy_odometer) {
        var ratio = retentionIndex(inp.buy_odometer, inp.retention_anchors)
                  / retentionIndex(v.observedAt, inp.retention_anchors);
        return { price: v.observedPrice * ratio, basis: 'derived' };
      }
      return { price: v.observedPrice, basis: 'observed' };
    }
    return { price: v.price, basis: 'placeholder' };
  }

  function costPerMile(v, inp) {
    var miles = inp.sell_odometer - inp.buy_odometer;
    var years = miles / inp.annual_miles;
    var anchors = inp.retention_anchors;

    var price = buyPrice(v, inp).price;
    var resaleMult = resaleMultiplier(v, inp);
    var ratio = retentionIndex(inp.sell_odometer, anchors)
              / retentionIndex(inp.buy_odometer, anchors);
    var resale = Math.min(price, price * ratio * resaleMult);

    var fuel = (v.fuel === 'Diesel' ? inp.diesel_per_gal : inp.gas_per_gal) / v.mpg;
    var tires = (v.tireClass === 'Truck' ? inp.tire_set_truck
                                         : inp.tire_set_crossover) / inp.tire_life_miles;

    var capital;
    if (inp.financing_mode === 'cash') {
      capital = (price + resale) / 2 * inp.cash_opportunity_rate;
    } else {
      var financed = price * (1 - inp.down_payment_pct);
      capital = financed * inp.avg_outstanding_balance_factor * inp.loan_apr
              + price * inp.down_payment_pct * inp.cash_opportunity_rate;
    }

    return (price - resale) / miles
         + fuel + tires
         + inp.scheduled_maint_per_mile
         + repairReserve(inp) * repairMultiplier(v, inp)
         + (inp.insurance_per_year + inp.registration_per_year) / inp.annual_miles
         + price * inp.sales_tax_rate / miles
         + capital * years / miles;
  }

  return {
    retentionIndex: retentionIndex,
    repairReserve: repairReserve,
    complaintScore: complaintScore,
    repairReliability: repairReliability,
    repairMultiplier: repairMultiplier,
    resaleMultiplier: resaleMultiplier,
    buyPrice: buyPrice,
    costPerMile: costPerMile
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VA;
