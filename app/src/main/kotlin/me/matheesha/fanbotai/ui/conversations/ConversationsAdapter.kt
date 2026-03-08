package me.matheesha.fanbotai.ui.conversations

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.model.Conversation
import me.matheesha.fanbotai.databinding.ItemConversationBinding

class ConversationsAdapter(
    private val onMuteToggle: (Conversation) -> Unit
) : ListAdapter<Conversation, ConversationsAdapter.ViewHolder>(DIFF) {

    inner class ViewHolder(private val b: ItemConversationBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: Conversation) {
            b.tvName.text        = item.name.ifEmpty { "User ${item.userId}" }
            b.tvUsername.text    = if (item.username.isNotEmpty()) "@${item.username}" else ""
            b.tvLastMessage.text = item.lastMessage.ifEmpty { "No messages" }
            b.tvMessageCount.text = "${item.messageCount} msgs · ${item.replyCount} replies"
            b.tvLastActive.text  = item.lastActive.take(16)

            val muteColor = if (item.muted)
                ContextCompat.getColor(b.root.context, R.color.status_offline)
            else
                ContextCompat.getColor(b.root.context, R.color.status_online)

            b.btnMute.text = if (item.muted) "Unmute" else "Mute"
            b.btnMute.setTextColor(muteColor)
            b.btnMute.setOnClickListener { onMuteToggle(item) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = ViewHolder(
        ItemConversationBinding.inflate(LayoutInflater.from(parent.context), parent, false)
    )

    override fun onBindViewHolder(holder: ViewHolder, position: Int) = holder.bind(getItem(position))

    companion object {
        val DIFF = object : DiffUtil.ItemCallback<Conversation>() {
            override fun areItemsTheSame(a: Conversation, b: Conversation) = a.userId == b.userId
            override fun areContentsTheSame(a: Conversation, b: Conversation) = a == b
        }
    }
}

