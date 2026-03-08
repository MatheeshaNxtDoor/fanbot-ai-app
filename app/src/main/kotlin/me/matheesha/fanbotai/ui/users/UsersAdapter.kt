package me.matheesha.fanbotai.ui.users

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import me.matheesha.fanbotai.data.model.DashboardUser
import me.matheesha.fanbotai.databinding.ItemUserBinding

class UsersAdapter(
    private val onDelete: (DashboardUser) -> Unit
) : ListAdapter<DashboardUser, UsersAdapter.ViewHolder>(DIFF) {

    inner class ViewHolder(private val b: ItemUserBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(user: DashboardUser) {
            b.tvUsername.text = user.username
            b.tvRole.text     = user.role
            b.tvPerms.text    = user.permissions.joinToString(", ").ifEmpty { "No permissions" }
            b.tv2fa.text      = if (user.totpEnabled) "2FA: On" else "2FA: Off"
            b.btnDelete.isEnabled = user.role != "admin"
            b.btnDelete.setOnClickListener { onDelete(user) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = ViewHolder(
        ItemUserBinding.inflate(LayoutInflater.from(parent.context), parent, false)
    )
    override fun onBindViewHolder(holder: ViewHolder, position: Int) = holder.bind(getItem(position))

    companion object {
        val DIFF = object : DiffUtil.ItemCallback<DashboardUser>() {
            override fun areItemsTheSame(a: DashboardUser, b: DashboardUser) = a.id == b.id
            override fun areContentsTheSame(a: DashboardUser, b: DashboardUser) = a == b
        }
    }
}

