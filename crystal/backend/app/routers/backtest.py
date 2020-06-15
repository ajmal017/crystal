from fastapi import APIRouter
from pydantic import BaseModel

import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import math
import json

router = APIRouter()


class backtestItem(BaseModel):
    allocation_weights: list
    codelist: list
    benchmark: str
    initial_amount: float
    start_date: str
    end_date: str
    rebalance: bool
    rebalance_frequency: str = None


@router.post("/")
def backtest(item: backtestItem):
    json_request = item.dict()
    allocation_weights = json_request['allocation_weights']
    initial_amount = json_request['initial_amount']
    start_date = json_request['start_date']
    end_date = json_request['end_date']
    codelist = json_request['codelist']
    benchmark = json_request['benchmark']
    rebalance = json_request['rebalance']
    if rebalance:
        rebalance_frequency = json_request['rebalance_frequency']

    month_frequency = {
        'Yearly': 12,
        'Quarterly': 3,
        'Monthly': 1
    }

    requestedCodes = ['date']
    requestedCodes = requestedCodes + codelist
    if benchmark != 'None':
        requestedCodes = requestedCodes + [benchmark]

    indexData = pd.read_csv('app/data/output.csv')
    indexData = indexData[requestedCodes]
    indexData = indexData.sort_values(by='date').reset_index(drop=True)

    indexData = indexData.rename(columns={indexData.columns[-1]: 'benchmark'})
    indexData = indexData[indexData['date'] >= start_date]
    indexData = indexData[indexData['date'] <= end_date]
    indexData = indexData.reset_index(drop=True)
    end_date = datetime.strptime(end_date, '%Y-%m-%d')
    start_date = datetime.strptime(start_date, '%Y-%m-%d')
    num_months = (end_date.year - start_date.year) * \
        12 + (end_date.month - start_date.month)
    if (end_date.day < start_date.day):
        num_months = num_months - 1

    rebalance_list = [start_date.strftime("%Y-%m-%d")]
    if rebalance:
        event_count = int(math.floor(
            num_months / month_frequency[rebalance_frequency]))
        rebalance_date = start_date
        for x in range(0, event_count):
            rebalance_date = rebalance_date + \
                relativedelta(months=+month_frequency[rebalance_frequency])
            rebalance_list.append(rebalance_date.strftime("%Y-%m-%d"))
    else:
        rebalance_list.append(end_date.strftime("%Y-%m-%d"))

    asset_projection = []

    initial_holding = initial_amount

    for x in range(0, len(rebalance_list)-1):
        asset_value = [x * initial_holding for x in allocation_weights]

        index_subset = indexData[indexData['date'] >=
                                 rebalance_list[x]][indexData['date'] <= rebalance_list[x+1]]
        index_subset = index_subset.sort_values(
            by='date').reset_index(drop=True)

        allocation = pd.DataFrame()
        for i in range(0, len(allocation_weights)):
            indexcode = index_subset.columns[i+1]
            scaling_factor = asset_value[i] / index_subset[indexcode][0]
            allocation[f'allocation {i}'] = index_subset[indexcode] * \
                scaling_factor

            if x != (len(rebalance_list)-1):
                allocation = allocation.iloc[:-1, :]

        asset_projection.append(allocation)

        initial_holding = allocation.iloc[len(allocation)-1].sum()

    asset_projection = pd.concat(asset_projection).reset_index(drop=True)
    asset_projection['output'] = asset_projection.sum(axis=1)
    asset_projection['date'] = indexData.sort_values(
        by='date').reset_index(drop=True)['date']

    if benchmark != 'None':
        scaling_factor = initial_amount / \
            indexData.sort_values(by='date').reset_index(
                drop=True)['benchmark'][0]
        asset_projection['benchmark'] = indexData.sort_values(
            by='date').reset_index(drop=True)['benchmark'] * scaling_factor

    # Calculate some metrics:
    start_end_ratio = asset_projection['output'][len(
        asset_projection)-1] / asset_projection['output'][0]
    no_years = (end_date - start_date).days / 365
    caGrowthRate = (start_end_ratio) ** (1/no_years) - 1

    asset_projection['outputreturn'] = (
        asset_projection['output'] - asset_projection['output'].shift(1))/asset_projection['output'].shift(1)
    meansubtracted_values = asset_projection['outputreturn'] - \
        asset_projection['outputreturn'].mean()
    meansubtracted_squared_sum = (meansubtracted_values**2).sum()
    variance = meansubtracted_squared_sum / \
        (len(asset_projection['outputreturn'])-1)
    stddev = variance ** (1/2)

    num_years = end_date.year - start_date.year + 1
    list_years = [start_date.year]
    for x in range(1, num_years):
        new_year = start_date.year + x
        list_years.append(new_year)

    annual_return_list = []
    for y in range(0, len(list_years)):
        CurrentYearIndex = asset_projection[asset_projection['date'].str.contains(
            str(list_years[y]))].reset_index(drop=True)['output']
        annual_return = (CurrentYearIndex[len(
            CurrentYearIndex)-1] - CurrentYearIndex[0]) / CurrentYearIndex[0]
        annual_return_list.append(annual_return)

    bestYear = max(annual_return_list)
    worstYear = min(annual_return_list)

    anuualreturns_df = pd.DataFrame({
        'year': list_years,
        'return': annual_return_list
    })

    short_asset_projection = asset_projection[['date', 'output']]
    previous_max = []
    for x in range(0, len(short_asset_projection)):
        previous_max.append(max(
            short_asset_projection[short_asset_projection['date'] <= short_asset_projection['date'][x]]['output']))

    asset_projection['previous_max'] = previous_max

    asset_projection['drawdown'] = asset_projection['output'] - \
        asset_projection['previous_max']
    asset_projection['drawdown_pct'] = asset_projection['drawdown'] / \
        asset_projection['previous_max']

    maxDrawdown = min(asset_projection['drawdown_pct'])

    output_field = ['date', 'output', 'drawdown_pct']

    if benchmark != 'None':
        output_field = output_field + ['benchmark']

    json_output = {

    }

    json_output['backtest'] = json.loads(
        asset_projection[output_field].to_json(orient='records'))
    json_output['metrics'] = {

    }
    json_output['metrics']['cagr'] = caGrowthRate
    json_output['metrics']['stddev'] = stddev
    json_output['metrics']['variance'] = variance
    json_output['metrics']['bestYear'] = bestYear
    json_output['metrics']['worstYear'] = worstYear
    json_output['metrics']['maxDrawdown'] = maxDrawdown
    json_output['metrics']['annual returns'] = json.loads(
        anuualreturns_df.to_json(orient='records'))

    return json_output
