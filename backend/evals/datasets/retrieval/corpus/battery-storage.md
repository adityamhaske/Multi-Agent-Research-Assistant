# Grid-scale battery storage

Grid batteries shift energy in time rather than generating it. Most utility installations
now use LFP cells — lithium iron phosphate — because the chemistry tolerates full cycling
better than nickel-rich alternatives and contains no cobalt. LFP gives up energy density
in exchange, which matters in a vehicle and hardly at all in a shipping container bolted
to a concrete pad.

A storage asset earns from several services at once: arbitrage between cheap and expensive
hours, frequency response measured in milliseconds, and capacity payments for being
available. Round-trip efficiency of eighty-five to ninety percent means a portion of every
stored unit is lost, so arbitrage only pays where the price spread exceeds that loss.

Degradation depends more on depth of discharge and temperature than on calendar age.

Thermal management drives both cost and lifetime. Cells held near the top of their
comfortable range age faster in a way that is roughly exponential, so a container in a hot
climate spends real energy on cooling purely to defer degradation. That parasitic load
counts against round-trip efficiency even though no cell ever sees it.

State of charge is estimated, not measured. Voltage under load says little on a flat
discharge curve, so controllers integrate current over time and correct against known
reference points, which is why a pack that never reaches a full charge slowly loses track
of where it is and has to be recalibrated.

Safety design assumes a cell will eventually fail. Propagation barriers, venting paths and
spacing exist so that one cell entering thermal runaway does not take its neighbours with
it, and that assumption shapes the enclosure more than the chemistry does.
