package me.matheesha.fanbotai.ui.analytics

import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.github.mikephil.charting.components.XAxis
import com.github.mikephil.charting.data.*
import com.github.mikephil.charting.formatter.IndexAxisValueFormatter
import com.google.android.material.snackbar.Snackbar
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Analytics
import me.matheesha.fanbotai.databinding.FragmentAnalyticsBinding
import me.matheesha.fanbotai.ui.UiState

class AnalyticsFragment : Fragment() {
    private var _binding: FragmentAnalyticsBinding? = null
    private val binding get() = _binding!!

    private val viewModel: AnalyticsViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return AnalyticsViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentAnalyticsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupCharts()
        binding.swipeRefresh.setOnRefreshListener { viewModel.load() }
        viewModel.analytics.observe(viewLifecycleOwner) { state ->
            binding.swipeRefresh.isRefreshing = state is UiState.Loading
            when (state) {
                is UiState.Success -> bindData(state.data)
                is UiState.Error   -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }
        viewModel.load()
    }

    private fun setupCharts() {
        val textColor = Color.parseColor("#B0B8D0")
        val gridColor = Color.parseColor("#222540")

        binding.chartDaily.apply {
            description.isEnabled = false; legend.isEnabled = false
            setBackgroundColor(Color.TRANSPARENT)
            xAxis.apply { position = XAxis.XAxisPosition.BOTTOM; this.textColor = textColor; this.gridColor = gridColor; granularity = 1f }
            axisLeft.apply { this.textColor = textColor; this.gridColor = gridColor }
            axisRight.isEnabled = false
        }
        binding.chartHourly.apply {
            description.isEnabled = false; legend.isEnabled = false
            setBackgroundColor(Color.TRANSPARENT)
            xAxis.apply { position = XAxis.XAxisPosition.BOTTOM; this.textColor = textColor; this.gridColor = gridColor; granularity = 1f; labelRotationAngle = -45f }
            axisLeft.apply { this.textColor = textColor; this.gridColor = gridColor }
            axisRight.isEnabled = false
        }
    }

    private fun bindData(data: Analytics) {
        val accent = Color.parseColor("#a855f7")
        binding.tvTotalMessages.text = data.summary.totalMessages.toString()
        binding.tvTotalReplies.text  = data.summary.totalReplies.toString()
        binding.tvTotalUsers.text    = data.summary.totalUsers.toString()
        binding.tvAvgPerDay.text     = data.summary.avgPerDay.toString()
        binding.tvTopUser.text       = "${data.summary.topUser} (${data.summary.topUserCount})"
        binding.tvPeakHour.text      = data.summary.peakHour
        binding.tvResponseRate.text  = "${data.summary.responseRate}%"
        binding.tvNewToday.text      = data.summary.newToday.toString()

        val dailyEntries = data.dailyValues.mapIndexed { i, v -> Entry(i.toFloat(), v.toFloat()) }
        val dailySet = LineDataSet(dailyEntries, "Messages").apply {
            color = accent; setCircleColor(accent); lineWidth = 2f; circleRadius = 4f
            setDrawFilled(true); fillColor = accent; fillAlpha = 30
            mode = LineDataSet.Mode.CUBIC_BEZIER
            valueTextColor = Color.parseColor("#B0B8D0")
        }
        binding.chartDaily.xAxis.valueFormatter = IndexAxisValueFormatter(data.dailyLabels.toTypedArray())
        binding.chartDaily.data = LineData(dailySet)
        binding.chartDaily.invalidate()

        val hourlyEntries = data.hourlyValues.mapIndexed { i, v -> BarEntry(i.toFloat(), v.toFloat()) }
        val hourlySet = BarDataSet(hourlyEntries, "Hourly").apply { color = Color.parseColor("#ec4899"); valueTextColor = Color.parseColor("#B0B8D0") }
        binding.chartHourly.xAxis.valueFormatter = IndexAxisValueFormatter(Array(24) { i -> "%02d".format(i) })
        binding.chartHourly.data = BarData(hourlySet)
        binding.chartHourly.invalidate()

        binding.tvTopChatters.text = data.topChatters.joinToString("\n") { "• ${it.name}: ${it.count}" }
    }

    override fun onDestroyView() { super.onDestroyView(); _binding = null }
}

