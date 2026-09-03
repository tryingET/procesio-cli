# Capacity sizing method

Estimate capacity from measured active work, concurrency, and service objectives—not from a generic action count.

## Inputs

- executions per period;
- peak arrival rate and burst duration;
- measured active compute time per representative execution;
- external wait behavior and whether it consumes metered/occupied capacity;
- required completion window;
- retry and exception rate;
- growth and safety margin;
- availability and maintenance assumptions.

## Calculations

For one workload class:

```text
active_seconds_per_period = executions × measured_active_seconds_per_execution
average_required_parallelism = active_seconds_per_period ÷ available_seconds_in_period
peak_required_parallelism = peak_arrival_rate × measured_elapsed_seconds_per_execution
planned_capacity = max(average_required_parallelism, peak_required_parallelism) × safety_factor
```

Use separate classes when one average hides materially different long and short runs. Show low/base/high scenarios and units.

## Commercial comparison

Obtain current prices and contractual terms before calculating costs. Compare like for like:

- included capacity and overage;
- concurrency/SLA guarantees;
- environments and support;
- infrastructure and operations for self-hosting;
- implementation and maintenance effort;
- expected growth and retry load.

State the price source and verification date. Never reuse a historical private quote as a public current price.
