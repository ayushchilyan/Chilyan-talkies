const socket = io();

const form = document.getElementById('chatForm');
const input = document.getElementById('msgInput');
const messages = document.getElementById('messages');

form.addEventListener('submit', e => {
    e.preventDefault();
    if(input.value.trim() === '') return;
    socket.emit('send_message', {receiver: window.friendName, message: input.value});
    input.value = '';
});

socket.on('new_message', data => {
    const div = document.createElement('div');
    div.className = data.sender === window.currentUser ? 'message sent' : 'message received';
    div.innerHTML = `<p>${data.message}</p><span>just now</span>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
});
