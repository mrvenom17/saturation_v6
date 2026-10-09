# Synthesis (pipeline v6.1.1, pre-registration d55d6b06)

Study set (pre-registration): 10 cities: Chennai_2015, Valencia_2024, EmiliaRomagna_2023a, Forli_2023b, York_2015, Carlisle_2015, PortoAlegre_2024, TaquariValley_2024, Houston_SanJacinto_2017, Jakarta_2020
- set 'tier A, all (confirmatory)': 9 cities: Carlisle_2015, Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024, York_2015
- set 'tier A, evaluable social layer (sensitivity, added in v6.1)': 7 cities: Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024
- set 'tier A, localisable (conditional)': 1 cities: Chennai_2015
- set 'tier A + A-points': 9 cities: Carlisle_2015, Chennai_2015, EmiliaRomagna_2023a, Forli_2023b, Houston_SanJacinto_2017, PortoAlegre_2024, TaquariValley_2024, Valencia_2024, York_2015
- set 'tier A + A-points, localisable': 1 cities: Chennai_2015
- set 'all localisable (any tier)': 2 cities: Chennai_2015, Jakarta_2020

## Read this first
- Carlisle_2015: layer = mixed signal (geotagged_photo 67%, news 33%); NO EVALUABLE SOCIAL LAYER (6 located mentions): its social effects are noise
- Chennai_2015: layer = news-media signal; label caveat: NRSC inundation zone as redistributed by OpenCity: the source states neither the satellite sensor nor the image date (dataset page re-checked 2 Oct 2026), so the label cannot be tied to a day of the event
- EmiliaRomagna_2023a: layer = mixed signal (news 79%, social_media 21%)
- Forli_2023b: layer = news-media signal
- Houston_SanJacinto_2017: layer = mixed signal (news 77%, social_media 23%, geotagged_photo 0%)
- Jakarta_2020: layer = news-media signal
- PortoAlegre_2024: layer = mixed signal (news 74%, social_media 26%)
- TaquariValley_2024: layer = mixed signal (news 76%, social_media 24%)
- Valencia_2024: layer = news-media signal
- York_2015: layer = mixed signal (news 56%, social_media 33%, geotagged_photo 11%); NO EVALUABLE SOCIAL LAYER (9 located mentions): its social effects are noise
- Verdicts are the pre-registered ones. 'reading' adds whether the whole 90% interval lies inside the SESOI: an effect can be non-zero and still negligible.
- A pooled interval inside the SESOI is not evidence from every city: see the weights and leave-one-out estimates in T11 before describing any pooled result.

RQ3 pooled slope [primary] info_nats_fm_adj: +0.0051 (95% CI +0.0001 to +0.0101; one-sided p (H1: slope < 0)=0.9763; k=9; I2=0.00; tau2=0; PI -0.000 to +0.010)
RQ3 pooled slope [primary] dAP_stacked_fm_adj: -0.0628 (95% CI -0.2568 to +0.1311; one-sided p (H1: slope < 0)=0.2382; k=9; I2=0.86; tau2=0.04285; PI -0.591 to +0.465)
RQ3 pooled slope [headroom_normalised] info_frac_fm_adj: +0.0131 (95% CI +0.0019 to +0.0243; one-sided p (H1: slope < 0)=0.9864; k=9; I2=0.22; tau2=0; PI +0.002 to +0.025)
RQ3 pooled slope [headroom_normalised] dAPh_fm_adj: -0.0609 (95% CI -0.3649 to +0.2430; one-sided p (H1: slope < 0)=0.3281; k=9; I2=0.85; tau2=0.09856; PI -0.866 to +0.744)
RQ3 pooled slope [robust_excl_R0] info_nats_fm_adj: -0.0027 (95% CI -0.0132 to +0.0078; one-sided p (H1: slope < 0)=0.2857; k=9; I2=0.00; tau2=2.18e-05; PI -0.018 to +0.013)
RQ3 pooled slope [robust_excl_R0] dAP_stacked_fm_adj: -0.0848 (95% CI -0.2713 to +0.1016; one-sided p (H1: slope < 0)=0.1624; k=9; I2=0.70; tau2=0.03245; PI -0.552 to +0.382)

RQ3 moderator [confirmatory] gradient slope info_nats_fm_adj ~ log_effective_locations: slope +0.0060 (SE 0.0147; KH p=0.6957; permutation p=0.4537; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0356 to +0.0178 (sign NOT stable; most influential TaquariValley_2024, slope without it -0.0356)
RQ3 moderator [confirmatory] gradient slope dAP_stacked_fm_adj ~ log_effective_locations: slope -0.1428 (SE 0.1217; KH p=0.2790; permutation p=0.2746; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.2566 to +0.0362 (sign NOT stable; most influential Chennai_2015, slope without it +0.0362)
RQ3 moderator [confirmatory] top-rung info_frac_fm ~ log_effective_locations: slope -0.0125 (SE 0.0101; KH p=0.2541; permutation p=0.4011; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0180 to -0.0024 (sign stable; most influential Chennai_2015, slope without it -0.0024)
RQ3 moderator [confirmatory] top-rung dAP_stacked_fm ~ log_effective_locations: slope -0.0143 (SE 0.0085; KH p=0.1373; permutation p=0.1784; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0197 to -0.0057 (sign stable; most influential York_2015, slope without it -0.0057)
RQ3 moderator [confirmatory] top-rung dAP_gated_fm ~ log_effective_locations: slope +0.0065 (SE 0.0077; KH p=0.4343; permutation p=0.5082; k=8); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0042 to +0.0229 (sign NOT stable; most influential Chennai_2015, slope without it +0.0229)
RQ3 moderator [confirmatory] top-rung dAP_early_fm ~ log_effective_locations: slope -0.0080 (SE 0.0051; KH p=0.1631; permutation p=0.0149; k=9); Holm p across the 7 confirmatory moderator tests=0.1046; leave-one-out slope -0.0098 to -0.0068 (sign stable; most influential TaquariValley_2024, slope without it -0.0098)
RQ3 moderator [confirmatory] top-rung dAP_adr_legacy_fm ~ log_effective_locations: slope +0.0113 (SE 0.0278; KH p=0.6971; permutation p=0.6720; k=9); Holm p across the 7 confirmatory moderator tests=1.0000; leave-one-out slope -0.0427 to +0.0623 (sign NOT stable; most influential Chennai_2015, slope without it -0.0427)
RQ3 moderator [sensitivity: evaluable social layer] gradient slope info_nats_fm_adj ~ log_effective_locations: slope +0.0107 (SE 0.0155; KH p=0.5208; permutation p=0.2976; k=7)
RQ3 moderator [sensitivity: evaluable social layer] gradient slope dAP_stacked_fm_adj ~ log_effective_locations: slope -0.1109 (SE 0.1399; KH p=0.4641; permutation p=0.4692; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung info_frac_fm ~ log_effective_locations: slope -0.0108 (SE 0.0094; KH p=0.3002; permutation p=0.4024; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_stacked_fm ~ log_effective_locations: slope -0.0050 (SE 0.0122; KH p=0.7016; permutation p=0.8187; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_gated_fm ~ log_effective_locations: slope +0.0088 (SE 0.0084; KH p=0.3581; permutation p=0.3486; k=6)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_early_fm ~ log_effective_locations: slope -0.0076 (SE 0.0053; KH p=0.2158; permutation p=0.0058; k=7)
RQ3 moderator [sensitivity: evaluable social layer] top-rung dAP_adr_legacy_fm ~ log_effective_locations: slope +0.0038 (SE 0.0281; KH p=0.8964; permutation p=0.8659; k=7)
RQ3 moderator [exploratory] gradient slope info_nats_fm_adj ~ physical_lift_top_rung: slope +0.0007 (SE 0.0010; KH p=0.4795; permutation p=0.2170; k=9)
RQ3 moderator [exploratory] gradient slope info_nats_fm_adj ~ log_mentions: slope -0.0009 (SE 0.0037; KH p=0.8116; permutation p=0.5855; k=9)
RQ3 moderator [exploratory] gradient slope dAP_stacked_fm_adj ~ physical_lift_top_rung: slope +0.0258 (SE 0.0159; KH p=0.1496; permutation p=0.1122; k=9)
RQ3 moderator [exploratory] gradient slope dAP_stacked_fm_adj ~ log_mentions: slope -0.0756 (SE 0.0301; KH p=0.0403; permutation p=0.0250; k=9)

Influence top-rung info_frac_fm: PortoAlegre_2024 41%, Houston_SanJacinto_2017 37% of the pooled weight; leave-one-out estimate from -0.0006 to +0.0030 (all cities +0.0019 [-0.0067, +0.0105])
Influence top-rung dAP_stacked_fm: PortoAlegre_2024 44%, Houston_SanJacinto_2017 37% of the pooled weight; leave-one-out estimate from +0.0007 to +0.0030 (all cities +0.0022 [-0.0056, +0.0100])
Influence top-rung dAP_gated_fm: Houston_SanJacinto_2017 42%, Forli_2023b 22% of the pooled weight; leave-one-out estimate from -0.0063 to +0.0006 (all cities -0.0032 [-0.0107, +0.0043])
Influence top-rung dAP_early_fm: PortoAlegre_2024 93%, Houston_SanJacinto_2017 5% of the pooled weight; leave-one-out estimate from +0.0003 to +0.0022 (all cities +0.0004 [-0.0011, +0.0018])
Influence top-rung dAP_adr_legacy_fm: Chennai_2015 13%, Forli_2023b 13% of the pooled weight; leave-one-out estimate from -0.0833 to -0.0678 (all cities -0.0740 [-0.1149, -0.0330])
Influence gradient slope info_nats_fm_adj: Houston_SanJacinto_2017 75%, Forli_2023b 17% of the pooled weight; leave-one-out estimate from +0.0047 to +0.0054 (all cities +0.0051 [+0.0001, +0.0101])
Influence gradient slope dAP_stacked_fm_adj: Forli_2023b 13%, York_2015 13% of the pooled weight; leave-one-out estimate from -0.0917 to +0.0244 (all cities -0.0628 [-0.2568, +0.1311])

RQ1 pooled top rung [tier A, all (confirmatory)] info_frac_fm: +0.0019 (95% CI -0.0067 to +0.0105; k=9; I2=0.61)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_stacked_fm: +0.0022 (95% CI -0.0056 to +0.0100; k=9; I2=0.76)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_gated_fm: -0.0032 (95% CI -0.0107 to +0.0043; k=8; I2=0.35)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_early_fm: +0.0004 (95% CI -0.0011 to +0.0018; k=9; I2=0.00)
RQ1 pooled top rung [tier A, all (confirmatory)] dAP_adr_legacy_fm: -0.0740 (95% CI -0.1149 to -0.0330; k=9; I2=0.95)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] info_frac_fm: +0.0015 (95% CI -0.0066 to +0.0097; k=7; I2=0.60)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_stacked_fm: +0.0013 (95% CI -0.0048 to +0.0073; k=7; I2=0.74)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_gated_fm: -0.0052 (95% CI -0.0161 to +0.0057; k=6; I2=0.53)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_early_fm: +0.0003 (95% CI -0.0012 to +0.0019; k=7; I2=0.00)
RQ1 pooled top rung [tier A, evaluable social layer (sensitivity, added in v6.1)] dAP_adr_legacy_fm: -0.0641 (95% CI -0.1094 to -0.0189; k=7; I2=0.96)

RQ2 Carlisle_2015 info_nats_fm_adj: slope -0.1042 [-0.8891, +0.3453], one-sided p=0.4232, Holm p=1.0000
RQ2 Carlisle_2015 dAP_stacked_fm_adj: slope +0.1894 [-0.0878, +0.5122], one-sided p=0.9182, Holm p=1.0000
RQ2 Chennai_2015 info_nats_fm_adj: slope -0.0573 [-0.1419, +0.0287], one-sided p=0.0878, Holm p=1.0000
RQ2 Chennai_2015 dAP_stacked_fm_adj: slope -0.4285 [-0.6050, -0.2677], one-sided p=0.0020, Holm p=0.0359
RQ2 EmiliaRomagna_2023a info_nats_fm_adj: slope -0.0262 [-0.1913, +0.0296], one-sided p=0.1238, Holm p=1.0000
RQ2 EmiliaRomagna_2023a dAP_stacked_fm_adj: slope -0.6940 [-1.0229, -0.0320], one-sided p=0.0220, Holm p=0.3513
RQ2 Forli_2023b info_nats_fm_adj: slope +0.0068 [-0.0012, +0.0169], one-sided p=0.9202, Holm p=1.0000
RQ2 Forli_2023b dAP_stacked_fm_adj: slope +0.0632 [+0.0109, +0.0994], one-sided p=0.9940, Holm p=1.0000
RQ2 Houston_SanJacinto_2017 info_nats_fm_adj: slope +0.0052 [+0.0004, +0.0099], one-sided p=0.9840, Holm p=1.0000
RQ2 Houston_SanJacinto_2017 dAP_stacked_fm_adj: slope -0.0286 [-0.1040, +0.0396], one-sided p=0.2315, Holm p=1.0000
RQ2 Jakarta_2020 info_nats_fm_adj: slope -0.0511 [-0.1290, -0.0002], one-sided p=0.0279 (not in the confirmatory family)
RQ2 Jakarta_2020 dAP_stacked_fm_adj: slope -0.3781 [-1.2500, -0.1769], one-sided p=0.0020 (not in the confirmatory family)
RQ2 PortoAlegre_2024 info_nats_fm_adj: slope +0.0039 [-0.0143, +0.0194], one-sided p=0.7186, Holm p=1.0000
RQ2 PortoAlegre_2024 dAP_stacked_fm_adj: slope +0.1253 [-0.0141, +0.2208], one-sided p=0.9621, Holm p=1.0000
RQ2 TaquariValley_2024 info_nats_fm_adj: slope -0.0415 [-0.0966, -0.0049], one-sided p=0.0120, Holm p=0.2036
RQ2 TaquariValley_2024 dAP_stacked_fm_adj: slope -0.0373 [-0.1239, +0.1152], one-sided p=0.4691, Holm p=1.0000
RQ2 Valencia_2024 info_nats_fm_adj: slope +0.0320 [-0.1949, +0.3079], one-sided p=0.5649, Holm p=1.0000
RQ2 Valencia_2024 dAP_stacked_fm_adj: slope -0.2405 [-0.4816, +0.0811], one-sided p=0.0858, Holm p=1.0000
RQ2 York_2015 info_nats_fm_adj: slope +0.0377 [-0.0219, +0.0852], one-sided p=0.8683, Holm p=1.0000
RQ2 York_2015 dAP_stacked_fm_adj: slope +0.1093 [+0.0639, +0.1876], one-sided p=1.0000, Holm p=1.0000

RQ1 Carlisle_2015 R5_+sar_event info_nats_fm: +0.0079 [-0.3901, +0.2591] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event info_frac_fm: +0.0146 [-0.5370, +0.5873] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_stacked_fm: +0.0109 [-0.0268, +0.0533] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_gated_fm: +0.0034 [-0.0213, +0.0585] -> inconclusive | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_early_fm: +0.0255 [+0.0072, +0.0733] -> informative | no evaluable social layer
RQ1 Carlisle_2015 R5_+sar_event dAP_adr_legacy_fm: -0.1582 [-0.2625, -0.0163] -> harmful | no evaluable social layer
RQ1 Chennai_2015 R5_+sar_event info_nats_fm: -0.0059 [-0.0166, +0.0026] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event info_frac_fm: -0.0117 [-0.0310, +0.0052] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_stacked_fm: -0.0120 [-0.0392, +0.0081] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_gated_fm: -0.0095 [-0.0350, +0.0109] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_early_fm: -0.0095 [-0.0307, +0.0112] -> inconclusive
RQ1 Chennai_2015 R5_+sar_event dAP_adr_legacy_fm: -0.0079 [-0.0159, +0.0024] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event info_nats_fm: -0.0078 [-0.0495, +0.0228] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event info_frac_fm: -0.0176 [-0.1006, +0.0623] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_stacked_fm: -0.1388 [-0.1620, +0.0174] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_gated_fm: -0.0109 [-0.0161, +0.0093] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_early_fm: +0.0022 [-0.0249, +0.0264] -> inconclusive
RQ1 EmiliaRomagna_2023a R5_+sar_event dAP_adr_legacy_fm: -0.0553 [-0.0777, +0.0049] -> inconclusive
RQ1 Forli_2023b R5_+sar_event info_nats_fm: +0.0006 [-0.0013, +0.0033] -> inconclusive
RQ1 Forli_2023b R5_+sar_event info_frac_fm: +0.0037 [-0.0081, +0.0193] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Forli_2023b R5_+sar_event dAP_stacked_fm: +0.0044 [-0.0046, +0.0148] -> inconclusive
RQ1 Forli_2023b R5_+sar_event dAP_gated_fm: +0.0005 [-0.0079, +0.0107] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Forli_2023b R5_+sar_event dAP_early_fm: +0.0036 [-0.0065, +0.0157] -> inconclusive
RQ1 Forli_2023b R5_+sar_event dAP_adr_legacy_fm: -0.0323 [-0.0445, -0.0168] -> harmful
RQ1 Houston_SanJacinto_2017 R5_+sar_event info_nats_fm: +0.0023 [+0.0009, +0.0037] -> inconclusive
RQ1 Houston_SanJacinto_2017 R5_+sar_event info_frac_fm: +0.0065 [+0.0026, +0.0105] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_stacked_fm: +0.0034 [+0.0012, +0.0060] -> informative | reading: negligible (non-zero but within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_gated_fm: +0.0009 [-0.0014, +0.0033] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_early_fm: +0.0020 [-0.0035, +0.0072] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 Houston_SanJacinto_2017 R5_+sar_event dAP_adr_legacy_fm: -0.1124 [-0.1342, -0.0904] -> harmful
RQ1 Jakarta_2020 R5_+sar_event info_nats_fm: -0.0014 [-0.0031, +0.0002] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event info_frac_fm: -0.0109 [-0.0263, +0.0012] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_stacked_fm: -0.0218 [-0.0276, -0.0098] -> harmful
RQ1 Jakarta_2020 R5_+sar_event dAP_gated_fm: -0.0045 [-0.0145, +0.0040] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_early_fm: -0.0098 [-0.0232, +0.0056] -> inconclusive
RQ1 Jakarta_2020 R5_+sar_event dAP_adr_legacy_fm: -0.0014 [-0.0033, +0.0010] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing info_nats_fm: -0.0001 [-0.0010, +0.0005] -> inconclusive
RQ1 PortoAlegre_2024 R4_+forcing info_frac_fm: -0.0005 [-0.0038, +0.0020] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_stacked_fm: -0.0001 [-0.0005, +0.0003] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_gated_fm: +0.0000 [+0.0000, +0.0000] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_early_fm: +0.0002 [-0.0009, +0.0017] -> saturated | reading: equivalent to zero (within SESOI)
RQ1 PortoAlegre_2024 R4_+forcing dAP_adr_legacy_fm: -0.1111 [-0.1302, -0.0869] -> harmful
RQ1 TaquariValley_2024 R4_+forcing info_nats_fm: -0.0113 [-0.0309, +0.0040] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing info_frac_fm: -0.0498 [-0.1223, +0.0241] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_stacked_fm: -0.0269 [-0.0469, +0.0263] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_gated_fm: -0.0370 [-0.0397, +0.0202] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_early_fm: +0.0095 [-0.0145, +0.0312] -> inconclusive
RQ1 TaquariValley_2024 R4_+forcing dAP_adr_legacy_fm: -0.0202 [-0.0378, -0.0043] -> harmful
RQ1 Valencia_2024 R5_+sar_event info_nats_fm: +0.0768 [-0.0230, +0.1728] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event info_frac_fm: +0.1793 [-0.0727, +0.3335] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_stacked_fm: +0.0383 [-0.0032, +0.1031] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_gated_fm: -0.0124 [-0.0326, +0.0276] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_early_fm: -0.0037 [-0.0238, +0.0823] -> inconclusive
RQ1 Valencia_2024 R5_+sar_event dAP_adr_legacy_fm: -0.1236 [-0.1481, -0.0517] -> harmful
RQ1 York_2015 R5_+sar_event info_nats_fm: +0.0337 [+0.0023, +0.0519] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event info_frac_fm: +0.1318 [+0.0092, +0.2247] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_stacked_fm: +0.0369 [+0.0252, +0.0699] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_gated_fm: +0.0042 [-0.0244, +0.0203] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_early_fm: -0.0090 [-0.0330, +0.0391] -> inconclusive | no evaluable social layer
RQ1 York_2015 R5_+sar_event dAP_adr_legacy_fm: -0.1361 [-0.2002, -0.0153] -> harmful | no evaluable social layer

Placebo Carlisle_2015 info_nats_fm_adj: real slope -0.1042 vs population-density slope -0.3560; Spearman(social, population) 0.99; social gain with population controlled at top rung +0.0201 [-0.4854, +0.5745] inconclusive
Placebo Carlisle_2015 dAP_stacked_fm_adj: real slope +0.1894 vs population-density slope +0.1584; Spearman(social, population) 0.99; social gain with population controlled at top rung +0.0080 [-0.0140, +0.0519] inconclusive
Placebo Chennai_2015 info_nats_fm_adj: real slope -0.0573 vs population-density slope -0.1748; Spearman(social, population) 0.80; social gain with population controlled at top rung -0.0130 [-0.0328, +0.0032] inconclusive
Placebo Chennai_2015 dAP_stacked_fm_adj: real slope -0.4285 vs population-density slope -0.7055; Spearman(social, population) 0.80; social gain with population controlled at top rung -0.0106 [-0.0355, +0.0088] inconclusive
Placebo EmiliaRomagna_2023a info_nats_fm_adj: real slope -0.0262 vs population-density slope +0.0041; Spearman(social, population) 0.82; social gain with population controlled at top rung -0.0211 [-0.1088, +0.0622] inconclusive
Placebo EmiliaRomagna_2023a dAP_stacked_fm_adj: real slope -0.6940 vs population-density slope -0.5305; Spearman(social, population) 0.82; social gain with population controlled at top rung -0.1430 [-0.1653, +0.0159] inconclusive
Placebo Forli_2023b info_nats_fm_adj: real slope +0.0068 vs population-density slope +0.0043; Spearman(social, population) 0.24; social gain with population controlled at top rung +0.0033 [-0.0080, +0.0185] saturated
Placebo Forli_2023b dAP_stacked_fm_adj: real slope +0.0632 vs population-density slope +0.0416; Spearman(social, population) 0.24; social gain with population controlled at top rung +0.0042 [-0.0047, +0.0142] inconclusive
Placebo Houston_SanJacinto_2017 info_nats_fm_adj: real slope +0.0052 vs population-density slope +0.0037; Spearman(social, population) 0.45; social gain with population controlled at top rung +0.0067 [+0.0025, +0.0112] informative
Placebo Houston_SanJacinto_2017 dAP_stacked_fm_adj: real slope -0.0286 vs population-density slope +0.0312; Spearman(social, population) 0.45; social gain with population controlled at top rung +0.0035 [+0.0012, +0.0063] informative
Placebo Jakarta_2020 info_nats_fm_adj: real slope -0.0511 vs population-density slope -0.1123; Spearman(social, population) 0.76; social gain with population controlled at top rung -0.0086 [-0.0241, +0.0038] inconclusive
Placebo Jakarta_2020 dAP_stacked_fm_adj: real slope -0.3781 vs population-density slope -0.4774; Spearman(social, population) 0.76; social gain with population controlled at top rung -0.0199 [-0.0237, -0.0105] harmful
Placebo PortoAlegre_2024 info_nats_fm_adj: real slope +0.0039 vs population-density slope +0.0435; Spearman(social, population) 0.51; social gain with population controlled at top rung +0.0002 [-0.0028, +0.0027] saturated
Placebo PortoAlegre_2024 dAP_stacked_fm_adj: real slope +0.1253 vs population-density slope +0.0297; Spearman(social, population) 0.51; social gain with population controlled at top rung -0.0000 [-0.0004, +0.0003] saturated
Placebo TaquariValley_2024 info_nats_fm_adj: real slope -0.0415 vs population-density slope -0.0067; Spearman(social, population) 0.91; social gain with population controlled at top rung -0.0549 [-0.1400, +0.0255] inconclusive
Placebo TaquariValley_2024 dAP_stacked_fm_adj: real slope -0.0373 vs population-density slope +0.0852; Spearman(social, population) 0.91; social gain with population controlled at top rung -0.0269 [-0.0497, +0.0190] inconclusive
Placebo Valencia_2024 info_nats_fm_adj: real slope +0.0320 vs population-density slope -0.0349; Spearman(social, population) 0.70; social gain with population controlled at top rung +0.1851 [-0.0834, +0.3456] inconclusive
Placebo Valencia_2024 dAP_stacked_fm_adj: real slope -0.2405 vs population-density slope +0.0142; Spearman(social, population) 0.70; social gain with population controlled at top rung +0.0423 [-0.0016, +0.1095] inconclusive
Placebo York_2015 info_nats_fm_adj: real slope +0.0377 vs population-density slope +0.0213; Spearman(social, population) 0.49; social gain with population controlled at top rung +0.1328 [+0.0116, +0.2299] inconclusive
Placebo York_2015 dAP_stacked_fm_adj: real slope +0.1093 vs population-density slope -0.2297; Spearman(social, population) 0.49; social gain with population controlled at top rung +0.0325 [+0.0187, +0.0684] inconclusive
