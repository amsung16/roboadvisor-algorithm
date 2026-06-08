#!/bin/bash
python etf_pipeline.py --update && python advisor.py --rebalance --profile B
