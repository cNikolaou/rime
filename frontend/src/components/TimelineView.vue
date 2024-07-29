<template>
  <div id="timeline">
    <v-chart class="chart" :option="option" />
  </div>
</template>

<style scoped>
#timeline {
  width: 80%;
}
</style>

<script setup>
import * as echarts from 'echarts';
import { use } from 'echarts/core';
import { SVGRenderer } from 'echarts/renderers';
import { PieChart } from 'echarts/charts';
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components';
import VChart from 'vue-echarts';
import { computed } from 'vue';
import { rawEventsSearchResult } from '../store';

use([SVGRenderer, PieChart, TitleComponent, TooltipComponent, LegendComponent]);

const option = computed(() => {
  if (
    !rawEventsSearchResult ||
    !rawEventsSearchResult.value ||
    !rawEventsSearchResult.value.events ||
    rawEventsSearchResult.value.events.events.length == 0
  ) {
    return {};
  }

  // Calculate the count of events annually (each key has a Map for
  // a specific year as their value)
  const eventCounts = new Map();
  let maxCount = 0;

  for (const event of rawEventsSearchResult.value.events.events) {
    const eventDate = event.timestamp.split('T')[0];
    const eventYear = eventDate.split('-')[0];

    if (!eventCounts.has(eventYear)) {
      eventCounts.set(eventYear, new Map());
    }
    const annualCounts = eventCounts.get(eventYear);

    if (!annualCounts.has(eventDate)) {
      annualCounts.set(eventDate, 0);
    }
    annualCounts.set(eventDate, annualCounts.get(eventDate) + 1);

    // maxCount is the count for the day with the max number of events
    maxCount = Math.max(maxCount, annualCounts.get(eventDate));
  }

  // Set the "calendar" and "series" options parameters for the Heatmap
  const calendar = [];
  const series = [];

  for (const [index, year] of [...eventCounts.keys()].entries()) {
    calendar.push({
      top: 180 * index + 80,
      range: year,
      cellSize: ['auto', 20],
    });

    series.push({
      type: 'heatmap',
      coordinateSystem: 'calendar',
      calendarIndex: index,
      data: [...eventCounts.get(year)],
    });
  }

  return {
    tooltip: {
      position: 'top',
    },
    visualMap: {
      min: 0,
      max: maxCount,
      orient: 'horizontal',
      left: 'center',
      top: 'top',
      // to be able to click on
      // calculable: true,
    },
    calendar: calendar,
    series: series,
  };
});
</script>

<style scoped>
.chart {
  height: 800px;
  margin-right: 150px;
}
</style>
