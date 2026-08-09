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

  function resaleMultiplier(v, inp) {
    return (1 - v.deprec5yr) / (1 - inp.industry_avg_5yr_deprec);
  }

  function buyPrice(v, inp) {
    if (v.observedPrice) {
      /* Scale along this vehicle's own curve from a measured point. No
         resaleMultiplier is involved -- that is what made the retired MSRP
         derivation double-penalise fast-depreciating models. At the anchor
         the ratio is exactly 1 and the observed figure passes through. */
      if (v.observedAt && v.observedAt !== inp.buy_odometer) {
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
         + repairReserve(inp)
         + (inp.insurance_per_year + inp.registration_per_year) / inp.annual_miles
         + price * inp.sales_tax_rate / miles
         + capital * years / miles;
  }

  return {
    retentionIndex: retentionIndex,
    repairReserve: repairReserve,
    resaleMultiplier: resaleMultiplier,
    buyPrice: buyPrice,
    costPerMile: costPerMile
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VA;
